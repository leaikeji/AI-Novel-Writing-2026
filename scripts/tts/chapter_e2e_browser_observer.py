#!/usr/bin/env python3
"""Strict Python boundary for the fixed T4-K Node browser observer.

The Node process owns the real browser.  This module accepts no URL, browser,
selector, viewport or module path from callers.  It validates the exact
digest-only report and converts the four in-memory PNG captures into the raw
observation DTO consumed by the internal controller host.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Final, Mapping

from scripts.tts.chapter_e2e_controller_host import (
    BrowserCaptureObservation,
    CalibrationObservation,
    _sha256_fixed_executable,
)
from scripts.tts.chapter_e2e_controller_trust import (
    CONTROLLER_ID,
    FIXED_REQUIRED_CAPTURES,
    canonical_json_bytes,
)
from scripts.tts.controller_node_runtime import (
    ControllerNodeRuntimeError,
    fixed_node_executable,
    verify_controller_node_environment,
)


OBSERVER_REQUEST_SCHEMA: Final = "moss-tts-t4k-browser-observer-request/1.0"
OBSERVER_REPORT_SCHEMA: Final = "moss-tts-t4k-browser-observer-report/1.2"
PENDING_GAP_NOT_OBSERVED_REASON_CODES: Final = frozenset(
    {
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
    }
)
FIXED_ORIGIN: Final = "http://127.0.0.1:18088"
FIXED_EDGE_PATH: Final = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
)
FIXED_EDGE_IDENTIFIER: Final = "com.microsoft.edgemac"
FIXED_EDGE_TEAM_IDENTIFIER: Final = "UBF8T346G9"
FIXED_NODE_VERSION: Final = "24.19.0"
FIXED_PLAYWRIGHT_CORE_VERSION: Final = "1.62.1"
MAX_REPORT_BYTES: Final = 128 * 1024 * 1024
MAX_SCREENSHOT_BYTES: Final = 32 * 1024 * 1024
MAX_SUMMARY_ROWS: Final = 512
OBSERVER_TIMEOUT_SECONDS: Final = 180
OBSERVER_ENTRYPOINT: Final = (
    Path(__file__).resolve().parent / "controller-node" / "bin" / "observe.mjs"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class BrowserObserverError(RuntimeError):
    """Fail-closed observer error exposing only a stable code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BrowserObservationRequest:
    novel_id: str
    document_id: str
    request_fingerprint_sha256: str
    run_fingerprint_sha256: str
    target_scope_sha256: str
    validation_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BrowserObserverExpectation:
    novel_id: str
    document_id: str
    request_fingerprint_sha256: str
    run_fingerprint_sha256: str
    target_scope_sha256: str
    node_executable_sha256: str
    edge_executable_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedBrowserObservation:
    captures: tuple[BrowserCaptureObservation, ...]
    layout_observations: tuple["BrowserLayoutObservation", ...]
    capture_console_error_counts: tuple[int, ...]
    report_sha256: str
    edge_executable_sha256: str
    node_executable_sha256: str
    network_request_count: int
    console_entry_count: int
    console_error_count: int
    page_error_count: int
    interaction_evidence: "BrowserInteractionEvidence"


@dataclass(frozen=True, slots=True)
class BrowserLayoutObservation:
    """Count-only layout facts for one exact viewport/assistant capture."""

    target_css_width: int
    target_css_height: int
    assistant_mode: str
    tracked_visible_region_count: int
    nonzero_overlap_pair_count: int
    horizontal_overflow_px: int


@dataclass(frozen=True, slots=True)
class BrowserInteractionEvidence:
    player_visible: bool
    editor_kind: str
    paragraph_context_menu_seek_observed: bool
    cursor_keyboard_seek_observed: bool
    latest_wins_observed: bool
    play_pause_rate_seek_observed: bool
    edit_restored: bool
    edit_tts_write_request_count: int
    media_http_observed: bool
    media_request_count: int
    pending_gap_status: str
    pending_gap_stop_before_observed: bool
    pending_gap_reason_code: str


def _fail() -> BrowserObserverError:
    return BrowserObserverError("BROWSER_OBSERVER_REPORT_INVALID")


def _node_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise _fail() from None


def _is_sha256(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _exact_mapping(value: object, keys: set[str]) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise _fail()
    return value


def _integer(value: object, *, minimum: int = 0, maximum: int = 2**31) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _fail()
    return value


def _summary(value: object) -> Mapping[str, object]:
    summary = _exact_mapping(
        value,
        {"count", "dropped_count", "rows", "summary_sha256"},
    )
    count = _integer(summary["count"])
    dropped = _integer(summary["dropped_count"])
    rows = summary["rows"]
    if (
        type(rows) is not list
        or len(rows) > MAX_SUMMARY_ROWS
        or count != len(rows) + dropped
        or not _is_sha256(summary["summary_sha256"])
    ):
        raise _fail()
    normalized: list[dict[str, str]] = []
    for raw in rows:
        row = _exact_mapping(raw, {"kind", "location_sha256", "message_sha256"})
        kind = row["kind"]
        if (
            type(kind) is not str
            or not 1 <= len(kind) <= 32
            or not _is_sha256(row["location_sha256"])
            or not _is_sha256(row["message_sha256"])
        ):
            raise _fail()
        normalized.append(
            {
                "kind": kind,
                "location_sha256": str(row["location_sha256"]),
                "message_sha256": str(row["message_sha256"]),
            }
        )
    if hashlib.sha256(_node_json_bytes(normalized)).hexdigest() != summary[
        "summary_sha256"
    ]:
        raise _fail()
    return summary


def _console_error_count(summary: Mapping[str, object]) -> int:
    """Count only browser console error-level rows, not harmless logs."""

    rows = summary["rows"]
    dropped = summary["dropped_count"]
    if type(rows) is not list or type(dropped) is not int:
        raise _fail()
    # A truncated summary cannot prove that the omitted entries were harmless,
    # so each dropped row contributes to the fail-closed error count.
    return dropped + sum(
        1
        for row in rows
        if type(row) is dict and row.get("kind") in {"assert", "error"}
    )


def _canonical_request(expectation: BrowserObserverExpectation) -> bytes:
    values = (
        expectation.request_fingerprint_sha256,
        expectation.run_fingerprint_sha256,
        expectation.target_scope_sha256,
        expectation.node_executable_sha256,
        expectation.edge_executable_sha256,
    )
    if (
        type(expectation) is not BrowserObserverExpectation
        or _UUID.fullmatch(expectation.novel_id) is None
        or _UUID.fullmatch(expectation.document_id) is None
        or any(not _is_sha256(value) for value in values)
    ):
        raise BrowserObserverError("BROWSER_OBSERVER_EXPECTATION_INVALID")
    return _node_json_bytes(
        {
            "document_id": expectation.document_id,
            "novel_id": expectation.novel_id,
            "request_fingerprint_sha256": (
                expectation.request_fingerprint_sha256
            ),
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "schema_version": OBSERVER_REQUEST_SCHEMA,
            "target_scope_sha256": expectation.target_scope_sha256,
        }
    ) + b"\n"


def _assistant(value: object, expected_mode: str) -> None:
    assistant = _exact_mapping(
        value,
        {
            "collapsed_attribute",
            "mode_attribute",
            "observed_mode",
            "toggle_aria_expanded",
        },
    )
    collapsed = expected_mode == "collapsed"
    if (
        assistant["collapsed_attribute"] != str(collapsed).lower()
        or assistant["observed_mode"] != expected_mode
        or assistant["toggle_aria_expanded"] != str(not collapsed).lower()
        or assistant["mode_attribute"] not in {"inline", "overlay"}
    ):
        raise _fail()


def _browser_identity(
    value: object,
    expectation: BrowserObserverExpectation,
) -> tuple[str, str]:
    identity = _exact_mapping(
        value,
        {
            "codesign",
            "edge_executable_path",
            "edge_executable_sha256",
            "js_version",
            "node_executable_sha256",
            "node_version",
            "playwright_core_version",
            "product",
            "protocol_version",
            "user_agent_sha256",
        },
    )
    codesign = _exact_mapping(
        identity["codesign"],
        {
            "cdhash",
            "deep_verified",
            "gatekeeper_accepted",
            "gatekeeper_override_security_disabled",
            "gatekeeper_result_sha256",
            "gatekeeper_source_notarized_developer_id",
            "identifier",
            "strict_result_sha256",
            "strict_verified",
            "team_identifier",
        },
    )
    string_fields = ("js_version", "product", "protocol_version")
    if (
        identity["edge_executable_path"] != FIXED_EDGE_PATH
        or identity["edge_executable_sha256"]
        != expectation.edge_executable_sha256
        or identity["node_executable_sha256"]
        != expectation.node_executable_sha256
        or identity["node_version"] != FIXED_NODE_VERSION
        or identity["playwright_core_version"]
        != FIXED_PLAYWRIGHT_CORE_VERSION
        or not _is_sha256(identity["user_agent_sha256"])
        or any(
            type(identity[field]) is not str or not identity[field]
            for field in string_fields
        )
        or codesign["identifier"] != FIXED_EDGE_IDENTIFIER
        or codesign["team_identifier"] != FIXED_EDGE_TEAM_IDENTIFIER
        or type(codesign["cdhash"]) is not str
        or not codesign["cdhash"]
        or codesign["deep_verified"] is not True
        or type(codesign["strict_verified"]) is not bool
        or codesign["gatekeeper_accepted"] is not True
        or type(codesign["gatekeeper_override_security_disabled"]) is not bool
        or codesign["gatekeeper_source_notarized_developer_id"] is not True
        or not _is_sha256(codesign["gatekeeper_result_sha256"])
        or not _is_sha256(codesign["strict_result_sha256"])
    ):
        raise _fail()
    return (
        str(identity["edge_executable_sha256"]),
        str(identity["node_executable_sha256"]),
    )


def _status(value: object) -> str:
    if value not in {"observed", "not_observed"}:
        raise _fail()
    return str(value)


def _interaction_evidence(value: object) -> BrowserInteractionEvidence:
    evidence = _exact_mapping(
        value,
        {
            "controls",
            "cursor_keyboard_seek",
            "edit_without_tts_write",
            "editor",
            "latest_wins",
            "media_http",
            "paragraph_context_menu_seek",
            "pending_gap",
            "player",
        },
    )
    seek_keys = {"command_dispatched", "elapsed_ms", "status", "target_changed"}
    context_seek = _exact_mapping(evidence["paragraph_context_menu_seek"], seek_keys)
    keyboard_seek = _exact_mapping(evidence["cursor_keyboard_seek"], seek_keys)
    for row in (context_seek, keyboard_seek):
        state = _status(row["status"])
        if (
            type(row["command_dispatched"]) is not bool
            or type(row["target_changed"]) is not bool
            or _integer(row["elapsed_ms"], maximum=120_000) < 0
            or (state == "observed" and row["command_dispatched"] is not True)
            or (state == "not_observed" and row["target_changed"] is not False)
        ):
            raise _fail()
    latest = _exact_mapping(
        evidence["latest_wins"],
        {
            "elapsed_ms",
            "final_target_won",
            "first_dispatch_observed",
            "second_dispatch_observed",
            "status",
        },
    )
    latest_state = _status(latest["status"])
    latest_bools = (
        latest["final_target_won"],
        latest["first_dispatch_observed"],
        latest["second_dispatch_observed"],
    )
    if (
        any(type(item) is not bool for item in latest_bools)
        or _integer(latest["elapsed_ms"], maximum=120_000) < 0
        or (latest_state == "observed" and latest_bools != (True, True, True))
        or (latest_state == "not_observed" and any(latest_bools))
    ):
        raise _fail()
    controls = _exact_mapping(
        evidence["controls"],
        {
            "elapsed_ms",
            "pause_observed",
            "play_observed",
            "rate_change_observed",
            "seek_observed",
            "status",
        },
    )
    control_state = _status(controls["status"])
    control_bools = tuple(
        controls[key]
        for key in (
            "play_observed",
            "pause_observed",
            "rate_change_observed",
            "seek_observed",
        )
    )
    if (
        any(type(item) is not bool for item in control_bools)
        or _integer(controls["elapsed_ms"], maximum=120_000) < 0
        or (control_state == "observed" and not any(control_bools))
        or (control_state == "not_observed" and any(control_bools))
    ):
        raise _fail()
    editor = _exact_mapping(
        evidence["editor"],
        {"codemirror_observed", "kind", "textarea_fallback_observed"},
    )
    editor_kind = editor["kind"]
    if (
        editor_kind not in {"codemirror6", "textarea-fallback", "not_observed"}
        or type(editor["codemirror_observed"]) is not bool
        or type(editor["textarea_fallback_observed"]) is not bool
        or editor["codemirror_observed"] is not (editor_kind == "codemirror6")
        or editor["textarea_fallback_observed"]
        is not (editor_kind == "textarea-fallback")
    ):
        raise _fail()
    edit = _exact_mapping(
        evidence["edit_without_tts_write"],
        {
            "after_sha256",
            "before_sha256",
            "editor_restored",
            "elapsed_ms",
            "status",
            "tts_write_request_count",
        },
    )
    edit_state = _status(edit["status"])
    if (
        not _is_sha256(edit["after_sha256"])
        or not _is_sha256(edit["before_sha256"])
        or type(edit["editor_restored"]) is not bool
        or _integer(edit["elapsed_ms"], maximum=120_000) < 0
        or _integer(edit["tts_write_request_count"], maximum=10_000) < 0
        or (edit_state == "observed" and edit["editor_restored"] is not True)
        or (
            edit_state == "observed"
            and edit["after_sha256"] != edit["before_sha256"]
        )
    ):
        raise _fail()
    media = _exact_mapping(
        evidence["media_http"],
        {
            "elapsed_ms",
            "etag_observed",
            "if_none_match_304",
            "if_range_206",
            "range_206",
            "request_count",
            "status",
            "unsatisfied_range_416",
        },
    )
    media_state = _status(media["status"])
    media_bools = tuple(
        media[key]
        for key in (
            "etag_observed",
            "if_none_match_304",
            "if_range_206",
            "range_206",
            "unsatisfied_range_416",
        )
    )
    media_count = _integer(media["request_count"], maximum=16)
    if (
        any(type(item) is not bool for item in media_bools)
        or _integer(media["elapsed_ms"], maximum=120_000) < 0
        or (media_state == "observed" and (not all(media_bools) or media_count != 5))
        or (media_state == "not_observed" and (any(media_bools) or media_count != 0))
    ):
        raise _fail()
    pending = _exact_mapping(
        evidence["pending_gap"],
        {"reason_code", "status", "stop_before_gap_observed"},
    )
    pending_state = _status(pending["status"])
    pending_reason = pending["reason_code"]
    pending_reasons = PENDING_GAP_NOT_OBSERVED_REASON_CODES | {"OBSERVED"}
    if (
        pending_reason not in pending_reasons
        or type(pending["stop_before_gap_observed"]) is not bool
        or (
            pending_state == "observed"
            and (
                pending["stop_before_gap_observed"] is not True
                or pending_reason != "OBSERVED"
            )
        )
        or (
            pending_state == "not_observed"
            and (
                pending["stop_before_gap_observed"] is not False
                or pending_reason == "OBSERVED"
            )
        )
    ):
        raise _fail()
    player = _exact_mapping(evidence["player"], {"visible"})
    if type(player["visible"]) is not bool:
        raise _fail()
    return BrowserInteractionEvidence(
        player_visible=bool(player["visible"]),
        editor_kind=str(editor_kind),
        paragraph_context_menu_seek_observed=(
            context_seek["status"] == "observed"
            and context_seek["target_changed"] is True
        ),
        cursor_keyboard_seek_observed=(
            keyboard_seek["status"] == "observed"
            and keyboard_seek["target_changed"] is True
        ),
        latest_wins_observed=latest_state == "observed",
        play_pause_rate_seek_observed=(
            control_state == "observed" and all(control_bools)
        ),
        edit_restored=edit_state == "observed" and edit["editor_restored"] is True,
        edit_tts_write_request_count=int(edit["tts_write_request_count"]),
        media_http_observed=media_state == "observed",
        media_request_count=media_count,
        pending_gap_status=pending_state,
        pending_gap_stop_before_observed=bool(pending["stop_before_gap_observed"]),
        pending_gap_reason_code=str(pending_reason),
    )


def _parse_browser_observer_report(
    raw: bytes,
    expectation: BrowserObserverExpectation,
) -> VerifiedBrowserObservation:
    """Parse one exact observer report; test seam for the fixed lifecycle."""

    _canonical_request(expectation)
    if type(raw) is not bytes or not 2 <= len(raw) <= MAX_REPORT_BYTES:
        raise _fail()
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail() from None
    report = _exact_mapping(
        decoded,
        {
            "browser_identity",
            "captures",
            "console_summary",
            "controller_id",
            "interaction_evidence",
            "network_summary",
            "page_error_summary",
            "report_sha256",
            "request_fingerprint_sha256",
            "route_evidence",
            "run_fingerprint_sha256",
            "schema_version",
            "target_scope_sha256",
        },
    )
    supplied_hash = report["report_sha256"]
    unsigned = dict(report)
    del unsigned["report_sha256"]
    if (
        report["schema_version"] != OBSERVER_REPORT_SCHEMA
        or report["controller_id"] != CONTROLLER_ID
        or report["request_fingerprint_sha256"]
        != expectation.request_fingerprint_sha256
        or report["run_fingerprint_sha256"]
        != expectation.run_fingerprint_sha256
        or report["target_scope_sha256"] != expectation.target_scope_sha256
        or not _is_sha256(supplied_hash)
        or hashlib.sha256(_node_json_bytes(unsigned)).hexdigest()
        != supplied_hash
        or raw != _node_json_bytes(report) + b"\n"
    ):
        raise _fail()
    edge_executable_sha256, node_executable_sha256 = _browser_identity(
        report["browser_identity"], expectation
    )
    route = _exact_mapping(
        report["route_evidence"],
        {"origin", "path_fingerprint_sha256", "query_fingerprint_sha256", "route_kind"},
    )
    expected_query = _node_json_bytes(
        {
            "document_id": expectation.document_id,
            "novel_id": expectation.novel_id,
            "novel_workbench": "1",
        }
    )
    if (
        route["origin"] != FIXED_ORIGIN
        or route["route_kind"] not in {"chat_root", "chat_session"}
        or not _is_sha256(route["path_fingerprint_sha256"])
        or route["query_fingerprint_sha256"]
        != hashlib.sha256(expected_query).hexdigest()
    ):
        raise _fail()
    console = _summary(report["console_summary"])
    network = _summary(report["network_summary"])
    page_errors = _summary(report["page_error_summary"])
    interactions = _interaction_evidence(report["interaction_evidence"])
    captures = report["captures"]
    if type(captures) is not list or len(captures) != len(FIXED_REQUIRED_CAPTURES):
        raise _fail()
    normalized: list[BrowserCaptureObservation] = []
    layout_observations: list[BrowserLayoutObservation] = []
    capture_console_error_counts: list[int] = []
    for raw_capture, required in zip(captures, FIXED_REQUIRED_CAPTURES, strict=True):
        width, height, mode = required
        capture = _exact_mapping(
            raw_capture,
            {
                "assistant",
                "calibration_attempts",
                "console_summary",
                "device_pixel_ratio",
                "layout_observation",
                "observed_inner_height",
                "observed_inner_width",
                "page_error_summary",
                "screenshot_bytes",
                "screenshot_pixel_height",
                "screenshot_pixel_width",
                "screenshot_png_base64",
                "screenshot_sha256",
                "target_css_height",
                "target_css_width",
            },
        )
        _assistant(capture["assistant"], mode)
        layout = _exact_mapping(
            capture["layout_observation"],
            {
                "horizontal_overflow_px",
                "nonzero_overlap_pair_count",
                "tracked_visible_region_count",
            },
        )
        layout_observations.append(
            BrowserLayoutObservation(
                target_css_width=width,
                target_css_height=height,
                assistant_mode=mode,
                tracked_visible_region_count=_integer(
                    layout["tracked_visible_region_count"]
                ),
                nonzero_overlap_pair_count=_integer(
                    layout["nonzero_overlap_pair_count"]
                ),
                horizontal_overflow_px=_integer(
                    layout["horizontal_overflow_px"]
                ),
            )
        )
        capture_console = _summary(capture["console_summary"])
        capture_errors = _summary(capture["page_error_summary"])
        capture_console_error_counts.append(
            _console_error_count(capture_console)
        )
        attempts = capture["calibration_attempts"]
        if type(attempts) is not list or not 1 <= len(attempts) <= 8:
            raise _fail()
        calibration: list[CalibrationObservation] = []
        for raw_attempt in attempts:
            attempt = _exact_mapping(
                raw_attempt,
                {
                    "observed_inner_height",
                    "observed_inner_width",
                    "requested_outer_height",
                    "requested_outer_width",
                },
            )
            calibration.append(
                CalibrationObservation(
                    requested_outer_width=_integer(
                        attempt["requested_outer_width"], minimum=1
                    ),
                    requested_outer_height=_integer(
                        attempt["requested_outer_height"], minimum=1
                    ),
                    observed_inner_width=_integer(
                        attempt["observed_inner_width"], minimum=1
                    ),
                    observed_inner_height=_integer(
                        attempt["observed_inner_height"], minimum=1
                    ),
                )
            )
        dpr = capture["device_pixel_ratio"]
        if type(dpr) not in {int, float} or not math.isfinite(dpr) or not 0.1 <= dpr <= 8:
            raise _fail()
        try:
            screenshot = base64.b64decode(
                capture["screenshot_png_base64"], validate=True
            )
        except (TypeError, ValueError, binascii.Error):
            raise _fail() from None
        if (
            not 33 <= len(screenshot) <= MAX_SCREENSHOT_BYTES
            or capture["screenshot_bytes"] != len(screenshot)
            or capture["screenshot_sha256"]
            != hashlib.sha256(screenshot).hexdigest()
            or capture["target_css_width"] != width
            or capture["target_css_height"] != height
            or capture["observed_inner_width"] != width
            or capture["observed_inner_height"] != height
        ):
            raise _fail()
        console_bytes = canonical_json_bytes(
            {"console": capture_console, "page_errors": capture_errors}
        )
        normalized.append(
            BrowserCaptureObservation(
                calibration_attempts=tuple(calibration),
                assistant_panel_expanded=mode == "expanded",
                device_pixel_ratio=float(dpr),
                screenshot_pixel_width=_integer(
                    capture["screenshot_pixel_width"], minimum=1
                ),
                screenshot_pixel_height=_integer(
                    capture["screenshot_pixel_height"], minimum=1
                ),
                screenshot_bytes=screenshot,
                console_summary_bytes=console_bytes,
                network_summary_bytes=canonical_json_bytes(network),
            )
        )
    return VerifiedBrowserObservation(
        captures=tuple(normalized),
        layout_observations=tuple(layout_observations),
        capture_console_error_counts=tuple(capture_console_error_counts),
        report_sha256=str(supplied_hash),
        edge_executable_sha256=edge_executable_sha256,
        node_executable_sha256=node_executable_sha256,
        network_request_count=int(network["count"]),
        console_entry_count=int(console["count"]),
        console_error_count=_console_error_count(console),
        page_error_count=int(page_errors["count"]),
        interaction_evidence=interactions,
    )


def _run_fixed_browser_observer(
    request: BrowserObservationRequest,
) -> VerifiedBrowserObservation:
    """Run the one fixed observer process; callable only by the lifecycle."""

    if type(request) is not BrowserObservationRequest:
        raise BrowserObserverError("BROWSER_OBSERVER_EXPECTATION_INVALID")
    if (
        type(request.validation_token) is not str
        or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", request.validation_token)
        is None
    ):
        raise BrowserObserverError("BROWSER_OBSERVER_EXPECTATION_INVALID")
    token_read: int | None = None
    token_write: int | None = None
    try:
        environment = verify_controller_node_environment()
        node = fixed_node_executable()
        entrypoint_details = OBSERVER_ENTRYPOINT.lstat()
        if (
            stat.S_ISLNK(entrypoint_details.st_mode)
            or not stat.S_ISREG(entrypoint_details.st_mode)
            or entrypoint_details.st_uid != os.getuid()
            or stat.S_IMODE(entrypoint_details.st_mode) & 0o022
        ):
            raise OSError
        runtime = environment["runtime"]
        if type(runtime) is not dict:
            raise OSError
        expectation = BrowserObserverExpectation(
            novel_id=request.novel_id,
            document_id=request.document_id,
            request_fingerprint_sha256=request.request_fingerprint_sha256,
            run_fingerprint_sha256=request.run_fingerprint_sha256,
            target_scope_sha256=request.target_scope_sha256,
            node_executable_sha256=str(runtime["node_executable_sha256"]),
            edge_executable_sha256=_sha256_fixed_executable(
                Path(FIXED_EDGE_PATH)
            ),
        )
        payload = _canonical_request(expectation)
        token_read, token_write = os.pipe()
        token_payload = request.validation_token.encode("ascii") + b"\n"
        if os.write(token_write, token_payload) != len(token_payload):
            raise OSError
        os.close(token_write)
        token_write = None

        def fixed_child_capability_fd() -> None:
            if token_read != 3:
                os.dup2(token_read, 3)
                os.close(token_read)

        completed = subprocess.run(
            [str(node), str(OBSERVER_ENTRYPOINT)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            pass_fds=(token_read,),
            preexec_fn=fixed_child_capability_fd,
            timeout=OBSERVER_TIMEOUT_SECONDS,
            check=False,
        )
    except (ControllerNodeRuntimeError, OSError, subprocess.SubprocessError):
        raise BrowserObserverError("BROWSER_OBSERVER_RUNTIME_HOLD") from None
    finally:
        if token_write is not None:
            os.close(token_write)
        if token_read is not None:
            os.close(token_read)
    if (
        completed.returncode != 0
        or completed.stderr
        or not 2 <= len(completed.stdout) <= MAX_REPORT_BYTES
    ):
        raise BrowserObserverError("BROWSER_OBSERVER_EXECUTION_HOLD")
    return _parse_browser_observer_report(completed.stdout, expectation)


__all__ = [
    "BrowserLayoutObservation",
    "BrowserObserverError",
    "BrowserObservationRequest",
    "BrowserInteractionEvidence",
    "BrowserObserverExpectation",
    "VerifiedBrowserObservation",
]
