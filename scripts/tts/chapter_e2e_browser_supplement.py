#!/usr/bin/env python3
"""Strict host boundary for the T4-GATE browser supplemental observer.

The supplemental process is deliberately independent from the sealed T4-K
observer run.  It reuses that observer's fixed browser identity and v1.2 base
report as an embedded, fully validated observation, while validating the new
manual-IME/lifecycle evidence in a separate v1.0 envelope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable, Final, Mapping

from scripts.tts.chapter_e2e_browser_observer import (
    BrowserObserverExpectation,
    VerifiedBrowserObservation,
    _parse_browser_observer_report,
)
from scripts.tts.chapter_e2e_controller_host import _sha256_fixed_executable
from scripts.tts.chapter_e2e_controller_trust import FIXED_REQUIRED_CAPTURES
from scripts.tts.controller_node_runtime import (
    ControllerNodeRuntimeError,
    fixed_node_executable,
    verify_controller_node_environment,
)


SUPPLEMENT_REQUEST_SCHEMA: Final = (
    "moss-tts-t4-gate-browser-supplement-request/1.0"
)
SUPPLEMENT_REPORT_SCHEMA: Final = (
    "moss-tts-t4-gate-browser-supplement-report/1.0"
)
SUPPLEMENT_CONTROLLER_ID: Final = (
    "ai-novel-world-2026-host-browser-supplement/1.0"
)
SYSTEM_IME_CHECKPOINT_ID: Final = "macos-system-chinese-ime/1"
TEXTAREA_FAULT_INJECTION_ID: Final = "codemirror-root-append-throw/1"
FIXED_EDGE_PATH: Final = (
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
)
SUPPLEMENT_ENTRYPOINT: Final = (
    Path(__file__).resolve().parent
    / "controller-node"
    / "bin"
    / "observe-supplement.mjs"
)
MAX_REPORT_BYTES: Final = 128 * 1024 * 1024
SUPPLEMENT_TIMEOUT_SECONDS: Final = 900
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


class BrowserSupplementError(RuntimeError):
    """Fail-closed supplemental observer error exposing only stable codes."""

    def __init__(self, code: str, recovery_status: str = "unknown") -> None:
        self.code = code
        self.recovery_status = recovery_status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class BrowserSupplementRequest:
    supplement_run_id: str
    novel_id: str
    primary_document_id: str
    secondary_document_id: str
    baseline_source_sha256: str
    fixture_manifest_sha256: str
    request_fingerprint_sha256: str
    target_scope_sha256: str
    validation_token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class BrowserSupplementExpectation:
    supplement_run_id: str
    novel_id: str
    primary_document_id: str
    secondary_document_id: str
    baseline_source_sha256: str
    fixture_manifest_sha256: str
    request_fingerprint_sha256: str
    target_scope_sha256: str
    node_executable_sha256: str
    edge_executable_sha256: str


@dataclass(frozen=True, slots=True)
class VerifiedBrowserSupplement:
    report_sha256: str
    base_observation: VerifiedBrowserObservation
    system_ime_capture_count: int
    textarea_fallback_observed: bool
    focus_aria_observed: bool
    progress_lifecycle_observed: bool
    chapter_switch_observed: bool
    old_draft_update_observed: bool
    recovery_status: str


def _fail() -> BrowserSupplementError:
    return BrowserSupplementError("BROWSER_SUPPLEMENT_REPORT_INVALID")


def _canonical(value: object) -> bytes:
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


def _is_sha(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def _exact(value: object, keys: set[str]) -> Mapping[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise _fail()
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise _fail()
    return value


def _integer(value: object, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise _fail()
    return value


def _request_values(expectation: BrowserSupplementExpectation) -> dict[str, str]:
    if (
        type(expectation) is not BrowserSupplementExpectation
        or _UUID.fullmatch(expectation.supplement_run_id) is None
        or _UUID.fullmatch(expectation.novel_id) is None
        or _UUID.fullmatch(expectation.primary_document_id) is None
        or _UUID.fullmatch(expectation.secondary_document_id) is None
        or expectation.primary_document_id == expectation.secondary_document_id
        or any(
            not _is_sha(value)
            for value in (
                expectation.baseline_source_sha256,
                expectation.fixture_manifest_sha256,
                expectation.request_fingerprint_sha256,
                expectation.target_scope_sha256,
                expectation.node_executable_sha256,
                expectation.edge_executable_sha256,
            )
        )
    ):
        raise BrowserSupplementError("BROWSER_SUPPLEMENT_EXPECTATION_INVALID")
    return {
        "baseline_source_sha256": expectation.baseline_source_sha256,
        "fixture_manifest_sha256": expectation.fixture_manifest_sha256,
        "novel_id": expectation.novel_id,
        "primary_document_id": expectation.primary_document_id,
        "request_fingerprint_sha256": expectation.request_fingerprint_sha256,
        "schema_version": SUPPLEMENT_REQUEST_SCHEMA,
        "secondary_document_id": expectation.secondary_document_id,
        "supplement_run_id": expectation.supplement_run_id,
        "target_scope_sha256": expectation.target_scope_sha256,
    }


def _canonical_request(expectation: BrowserSupplementExpectation) -> bytes:
    return _canonical(_request_values(expectation)) + b"\n"


def _base_run_fingerprint(expectation: BrowserSupplementExpectation) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "fixture_manifest_sha256": expectation.fixture_manifest_sha256,
                "supplement_run_id": expectation.supplement_run_id,
            }
        )
    ).hexdigest()


def _ime(value: object, *, editor_kind: str) -> None:
    item = _exact(
        value,
        {
            "after_sha256",
            "before_sha256",
            "checkpoint_id",
            "committed_sha256",
            "editor_kind",
            "editor_restored",
            "focus_preserved_during_composition",
            "han_character_count_delta",
            "input_source_class",
            "operator_confirmed",
            "playback_seek_during_composition_count",
            "selection_preserved_or_expected",
            "status",
            "trusted_counts",
            "tts_write_request_count",
            "untrusted_event_count",
        },
    )
    counts = _exact(
        item["trusted_counts"],
        {"compositionend", "compositionstart", "compositionupdate"},
    )
    if (
        item["checkpoint_id"] != SYSTEM_IME_CHECKPOINT_ID
        or item["editor_kind"] != editor_kind
        or item["input_source_class"] != "system_chinese"
        or item["status"] != "observed"
        or item["operator_confirmed"] is not True
        or item["editor_restored"] is not True
        or item["focus_preserved_during_composition"] is not True
        or item["playback_seek_during_composition_count"] != 0
        or item["selection_preserved_or_expected"] is not True
        or item["tts_write_request_count"] != 0
        or item["untrusted_event_count"] != 0
        or _integer(item["han_character_count_delta"], 1) < 1
        or any(_integer(counts[key], 1) < 1 for key in counts)
        or not _is_sha(item["before_sha256"])
        or not _is_sha(item["committed_sha256"])
        or not _is_sha(item["after_sha256"])
        or item["before_sha256"] != item["after_sha256"]
        or item["committed_sha256"] == item["before_sha256"]
    ):
        raise _fail()


def _focus_capture(value: object, expected: tuple[int, int, str]) -> None:
    item = _exact(
        value,
        {
            "all_control_names_nonempty",
            "all_controls_keyboard_reachable",
            "assistant_mode",
            "control_count",
            "target_css_height",
            "target_css_width",
        },
    )
    width, height, mode = expected
    if (
        item["target_css_width"] != width
        or item["target_css_height"] != height
        or item["assistant_mode"] != mode
        or item["all_control_names_nonempty"] is not True
        or item["all_controls_keyboard_reachable"] is not True
        or _integer(item["control_count"], 1) < 1
    ):
        raise _fail()


def _parse_browser_supplement_report(
    raw: bytes,
    expectation: BrowserSupplementExpectation,
    *,
    parse_base: Callable[
        [bytes, BrowserObserverExpectation], VerifiedBrowserObservation
    ] = _parse_browser_observer_report,
) -> VerifiedBrowserSupplement:
    if (
        not isinstance(raw, bytes)
        or not 2 <= len(raw) <= MAX_REPORT_BYTES
        or raw[-1:] != b"\n"
    ):
        raise _fail()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail() from None
    report = _exact(
        value,
        {
            "base_observation",
            "browser_identity",
            "captures",
            "chapter_switch",
            "controller_id",
            "fixture_manifest_sha256",
            "focus_aria",
            "novel_id",
            "old_draft_update",
            "primary_document_id",
            "progress_lifecycle",
            "recovery",
            "report_sha256",
            "request_fingerprint_sha256",
            "route_evidence",
            "schema_version",
            "secondary_document_id",
            "supplement_run_id",
            "system_ime",
            "target_scope_sha256",
            "textarea_fallback",
        },
    )
    supplied_hash = report["report_sha256"]
    unsigned = {key: item for key, item in report.items() if key != "report_sha256"}
    if (
        _canonical(report) + b"\n" != raw
        or not _is_sha(supplied_hash)
        or hashlib.sha256(_canonical(unsigned)).hexdigest() != supplied_hash
        or report["schema_version"] != SUPPLEMENT_REPORT_SCHEMA
        or report["controller_id"] != SUPPLEMENT_CONTROLLER_ID
        or report["supplement_run_id"] != expectation.supplement_run_id
        or report["novel_id"] != expectation.novel_id
        or report["primary_document_id"] != expectation.primary_document_id
        or report["secondary_document_id"] != expectation.secondary_document_id
        or report["fixture_manifest_sha256"]
        != expectation.fixture_manifest_sha256
        or report["request_fingerprint_sha256"]
        != expectation.request_fingerprint_sha256
        or report["target_scope_sha256"] != expectation.target_scope_sha256
    ):
        raise _fail()

    base_expectation = BrowserObserverExpectation(
        novel_id=expectation.novel_id,
        document_id=expectation.primary_document_id,
        request_fingerprint_sha256=expectation.request_fingerprint_sha256,
        run_fingerprint_sha256=_base_run_fingerprint(expectation),
        target_scope_sha256=expectation.target_scope_sha256,
        node_executable_sha256=expectation.node_executable_sha256,
        edge_executable_sha256=expectation.edge_executable_sha256,
    )
    base = parse_base(
        _canonical(report["base_observation"]) + b"\n",
        base_expectation,
    )
    base_raw = report["base_observation"]
    if (
        type(base_raw) is not dict
        or report["browser_identity"] != base_raw.get("browser_identity")
        or report["route_evidence"] != base_raw.get("route_evidence")
        or type(report["captures"]) is not list
        or len(report["captures"]) != 4
        or type(base_raw.get("captures")) is not list
        or len(base_raw["captures"]) != 4
    ):
        raise _fail()
    for capture, base_capture, (width, height, mode) in zip(
        report["captures"],
        base_raw["captures"],
        FIXED_REQUIRED_CAPTURES,
        strict=True,
    ):
        row = _exact(
            capture,
            {
                "assistant_mode",
                "console_count",
                "console_dropped_count",
                "console_summary_sha256",
                "device_pixel_ratio",
                "horizontal_overflow_px",
                "nonzero_overlap_pair_count",
                "observed_inner_height",
                "observed_inner_width",
                "page_error_count",
                "page_error_dropped_count",
                "page_error_summary_sha256",
                "screenshot_bytes",
                "screenshot_pixel_height",
                "screenshot_pixel_width",
                "screenshot_sha256",
                "target_css_height",
                "target_css_width",
            },
        )
        if type(base_capture) is not dict:
            raise _fail()
        if (
            row["target_css_width"] != width
            or row["target_css_height"] != height
            or row["observed_inner_width"] != width
            or row["observed_inner_height"] != height
            or row["assistant_mode"] != mode
            or row["screenshot_bytes"] != base_capture.get("screenshot_bytes")
            or row["screenshot_pixel_width"]
            != base_capture.get("screenshot_pixel_width")
            or row["screenshot_pixel_height"]
            != base_capture.get("screenshot_pixel_height")
            or row["screenshot_sha256"] != base_capture.get("screenshot_sha256")
            or row["console_summary_sha256"]
            != base_capture.get("console_summary", {}).get("summary_sha256")
            or row["page_error_summary_sha256"]
            != base_capture.get("page_error_summary", {}).get("summary_sha256")
            or not _is_sha(row["screenshot_sha256"])
            or not _is_sha(row["console_summary_sha256"])
            or not _is_sha(row["page_error_summary_sha256"])
            or _integer(row["screenshot_bytes"], 1) < 1
            or _integer(row["console_count"]) < 0
            or _integer(row["console_dropped_count"]) < 0
            or _integer(row["page_error_count"]) < 0
            or _integer(row["page_error_dropped_count"]) < 0
            or _integer(row["horizontal_overflow_px"]) < 0
            or _integer(row["nonzero_overlap_pair_count"]) < 0
        ):
            raise _fail()

    system_ime = report["system_ime"]
    if type(system_ime) is not list or len(system_ime) != 4:
        raise _fail()
    for item, (width, height, mode) in zip(
        system_ime, FIXED_REQUIRED_CAPTURES, strict=True
    ):
        row = _exact(
            item,
            set(item) if type(item) is dict else set(),
        )
        if (
            row.get("target_css_width") != width
            or row.get("target_css_height") != height
            or row.get("assistant_mode") != mode
        ):
            raise _fail()
        _ime(
            {key: value for key, value in row.items() if key not in {
                "target_css_width", "target_css_height", "assistant_mode"
            }},
            editor_kind="codemirror6",
        )

    textarea = _exact(
        report["textarea_fallback"],
        {
            "accessible_name_nonempty",
            "audio_playable",
            "code_mirror_absent",
            "fault_injection_count",
            "fault_injection_id",
            "gutter_count",
            "ime",
            "sentinels",
            "status",
            "textarea_visible",
        },
    )
    if (
        textarea["status"] != "observed"
        or textarea["fault_injection_id"] != TEXTAREA_FAULT_INJECTION_ID
        or textarea["fault_injection_count"] != 1
        or textarea["accessible_name_nonempty"] is not True
        or textarea["audio_playable"] is not True
        or textarea["code_mirror_absent"] is not True
        or textarea["textarea_visible"] is not True
        or textarea["gutter_count"] != 0
        or type(textarea["sentinels"]) is not list
        or len(textarea["sentinels"]) != 4
    ):
        raise _fail()
    _ime(textarea["ime"], editor_kind="textarea-fallback")
    for sentinel, expected in zip(
        textarea["sentinels"], FIXED_REQUIRED_CAPTURES, strict=True
    ):
        row = _exact(
            sentinel,
            {
                "assistant_mode",
                "code_mirror_absent",
                "focus_aria",
                "observed_inner_height",
                "observed_inner_width",
                "target_css_height",
                "target_css_width",
                "textarea_visible",
            },
        )
        width, height, mode = expected
        if (
            row["target_css_width"] != width
            or row["target_css_height"] != height
            or row["observed_inner_width"] != width
            or row["observed_inner_height"] != height
            or row["assistant_mode"] != mode
            or row["code_mirror_absent"] is not True
            or row["textarea_visible"] is not True
        ):
            raise _fail()
        focus = _exact(
            row["focus_aria"],
            {
                "all_control_names_nonempty",
                "all_controls_keyboard_reachable",
                "control_count",
            },
        )
        if (
            focus["all_control_names_nonempty"] is not True
            or focus["all_controls_keyboard_reachable"] is not True
            or _integer(focus["control_count"], 1) < 1
        ):
            raise _fail()

    focus_aria = _exact(
        report["focus_aria"],
        {
            "all_control_names_nonempty",
            "all_visible_enabled_controls_keyboard_reachable",
            "captures",
            "context_menu_focus_observed",
            "editor_focus_restored",
            "focus_visible_style_observed",
            "live_region_polite",
            "review",
            "visible_enabled_control_count",
        },
    )
    review = _exact(
        focus_aria["review"],
        {
            "aria_references_exist",
            "dialog_focus_observed",
            "trigger_focus_restored",
        },
    )
    if (
        any(
            focus_aria[key] is not True
            for key in (
                "all_control_names_nonempty",
                "all_visible_enabled_controls_keyboard_reachable",
                "context_menu_focus_observed",
                "editor_focus_restored",
                "focus_visible_style_observed",
                "live_region_polite",
            )
        )
        or any(value is not True for value in review.values())
        or _integer(focus_aria["visible_enabled_control_count"], 1) < 1
        or type(focus_aria["captures"]) is not list
        or len(focus_aria["captures"]) != 4
    ):
        raise _fail()
    for capture, expected in zip(
        focus_aria["captures"], FIXED_REQUIRED_CAPTURES, strict=True
    ):
        _focus_capture(capture, expected)

    progress = _exact(
        report["progress_lifecycle"],
        {
            "baseline_projection_sha256",
            "close_reopen_restored",
            "edition_id_sha256",
            "offset_tolerance_ms",
            "progress_put_observed",
            "reload_restored",
            "restored_projection_sha256",
            "status",
        },
    )
    if (
        progress["status"] != "observed"
        or progress["close_reopen_restored"] is not True
        or progress["progress_put_observed"] is not True
        or progress["reload_restored"] is not True
        or progress["offset_tolerance_ms"] != 1500
        or any(
            not _is_sha(progress[key])
            for key in (
                "baseline_projection_sha256",
                "edition_id_sha256",
                "restored_projection_sha256",
            )
        )
    ):
        raise _fail()

    chapter = _exact(
        report["chapter_switch"],
        {
            "generation_a",
            "generation_b",
            "generation_return",
            "player_a_inactive_on_b",
            "primary_edition_id_sha256",
            "restored_same_edition",
            "stale_primary_action_count",
            "status",
        },
    )
    generation_a = _integer(chapter["generation_a"], 1)
    generation_b = _integer(chapter["generation_b"], generation_a + 1)
    _integer(chapter["generation_return"], generation_b + 1)
    if (
        chapter["status"] != "observed"
        or chapter["player_a_inactive_on_b"] is not True
        or chapter["restored_same_edition"] is not True
        or chapter["stale_primary_action_count"] != 0
        or not _is_sha(chapter["primary_edition_id_sha256"])
    ):
        raise _fail()

    old_draft = _exact(
        report["old_draft_update"],
        {
            "automatic_tts_write_count",
            "baseline_edition_unchanged",
            "controlled_update_response_status",
            "draft_write_count",
            "explicit_update_intent",
            "gutter_update_required_observed",
            "old_audio_remained_available",
            "old_draft_marker_visible",
            "source_restored",
            "status",
            "synthesis_completed_claimed",
        },
    )
    if (
        old_draft["status"] != "observed"
        or old_draft["automatic_tts_write_count"] != 0
        or old_draft["baseline_edition_unchanged"] is not True
        or old_draft["controlled_update_response_status"] != 503
        or _integer(old_draft["draft_write_count"]) < 0
        or old_draft["explicit_update_intent"] != "update"
        or old_draft["gutter_update_required_observed"] is not True
        or old_draft["old_audio_remained_available"] is not True
        or old_draft["old_draft_marker_visible"] is not True
        or old_draft["source_restored"] is not True
        or old_draft["synthesis_completed_claimed"] is not False
    ):
        raise _fail()

    recovery = _exact(
        report["recovery"],
        {"baseline_source_sha256", "final_source_sha256", "status"},
    )
    if (
        recovery["status"] != "restored"
        or recovery["baseline_source_sha256"]
        != expectation.baseline_source_sha256
        or recovery["final_source_sha256"]
        != expectation.baseline_source_sha256
    ):
        raise _fail()
    return VerifiedBrowserSupplement(
        report_sha256=str(supplied_hash),
        base_observation=base,
        system_ime_capture_count=4,
        textarea_fallback_observed=True,
        focus_aria_observed=True,
        progress_lifecycle_observed=True,
        chapter_switch_observed=True,
        old_draft_update_observed=True,
        recovery_status="restored",
    )


def _parse_hold(raw: bytes) -> BrowserSupplementError:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return BrowserSupplementError("BROWSER_SUPPLEMENT_EXECUTION_HOLD")
    if (
        type(value) is not dict
        or set(value) != {"error_code", "recovery_status", "status"}
        or value.get("status") != "hold"
        or type(value.get("error_code")) is not str
        or not re.fullmatch(r"[A-Z0-9_]{3,96}", value["error_code"])
        or value.get("recovery_status")
        not in {"not_required", "restored", "failed", "unknown"}
        or _canonical(value) + b"\n" != raw
    ):
        return BrowserSupplementError("BROWSER_SUPPLEMENT_EXECUTION_HOLD")
    return BrowserSupplementError(
        str(value["error_code"]), str(value["recovery_status"])
    )


def run_browser_supplement(
    request: BrowserSupplementRequest,
) -> VerifiedBrowserSupplement:
    """Run the fixed headed observer; system Chinese IME remains operator-only."""

    if (
        type(request) is not BrowserSupplementRequest
        or _TOKEN.fullmatch(request.validation_token) is None
    ):
        raise BrowserSupplementError("BROWSER_SUPPLEMENT_EXPECTATION_INVALID")
    token_read: int | None = None
    token_write: int | None = None
    try:
        environment = verify_controller_node_environment()
        node = fixed_node_executable()
        details = SUPPLEMENT_ENTRYPOINT.lstat()
        if (
            stat.S_ISLNK(details.st_mode)
            or not stat.S_ISREG(details.st_mode)
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) & 0o022
        ):
            raise OSError
        runtime = environment["runtime"]
        if type(runtime) is not dict:
            raise OSError
        expectation = BrowserSupplementExpectation(
            supplement_run_id=request.supplement_run_id,
            novel_id=request.novel_id,
            primary_document_id=request.primary_document_id,
            secondary_document_id=request.secondary_document_id,
            baseline_source_sha256=request.baseline_source_sha256,
            fixture_manifest_sha256=request.fixture_manifest_sha256,
            request_fingerprint_sha256=request.request_fingerprint_sha256,
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
            [str(node), str(SUPPLEMENT_ENTRYPOINT)],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            pass_fds=(token_read,),
            preexec_fn=fixed_child_capability_fd,
            timeout=SUPPLEMENT_TIMEOUT_SECONDS,
            check=False,
        )
    except (ControllerNodeRuntimeError, OSError, subprocess.SubprocessError):
        raise BrowserSupplementError("BROWSER_SUPPLEMENT_RUNTIME_HOLD") from None
    finally:
        if token_write is not None:
            os.close(token_write)
        if token_read is not None:
            os.close(token_read)
    if completed.returncode != 0:
        if completed.stdout or not 2 <= len(completed.stderr) <= 1024:
            raise BrowserSupplementError("BROWSER_SUPPLEMENT_EXECUTION_HOLD")
        raise _parse_hold(completed.stderr)
    if completed.stderr or not 2 <= len(completed.stdout) <= MAX_REPORT_BYTES:
        raise BrowserSupplementError("BROWSER_SUPPLEMENT_EXECUTION_HOLD")
    return _parse_browser_supplement_report(completed.stdout, expectation)


__all__ = [
    "BrowserSupplementError",
    "BrowserSupplementExpectation",
    "BrowserSupplementRequest",
    "VerifiedBrowserSupplement",
    "run_browser_supplement",
]
