from __future__ import annotations

import hashlib
import json

import pytest

from scripts.tts.chapter_e2e_browser_supplement import (
    BrowserSupplementError,
    BrowserSupplementExpectation,
    SUPPLEMENT_CONTROLLER_ID,
    SUPPLEMENT_REPORT_SCHEMA,
    SYSTEM_IME_CHECKPOINT_ID,
    TEXTAREA_FAULT_INJECTION_ID,
    _base_run_fingerprint,
    _canonical_request,
    _parse_browser_supplement_report,
    _parse_hold,
)
from scripts.tts.chapter_e2e_controller_trust import FIXED_REQUIRED_CAPTURES


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _expectation() -> BrowserSupplementExpectation:
    return BrowserSupplementExpectation(
        supplement_run_id="44444444-4444-4444-8444-444444444444",
        novel_id="11111111-1111-4111-8111-111111111111",
        primary_document_id="22222222-2222-4222-8222-222222222222",
        secondary_document_id="33333333-3333-4333-8333-333333333333",
        baseline_source_sha256="a" * 64,
        fixture_manifest_sha256="b" * 64,
        request_fingerprint_sha256="c" * 64,
        target_scope_sha256="d" * 64,
        node_executable_sha256="e" * 64,
        edge_executable_sha256="f" * 64,
    )


def _ime(kind: str) -> dict[str, object]:
    return {
        "after_sha256": "a" * 64,
        "before_sha256": "a" * 64,
        "checkpoint_id": SYSTEM_IME_CHECKPOINT_ID,
        "committed_sha256": "9" * 64,
        "editor_kind": kind,
        "editor_restored": True,
        "focus_preserved_during_composition": True,
        "han_character_count_delta": 2,
        "input_source_class": "system_chinese",
        "operator_confirmed": True,
        "playback_seek_during_composition_count": 0,
        "selection_preserved_or_expected": True,
        "status": "observed",
        "trusted_counts": {
            "compositionend": 1,
            "compositionstart": 1,
            "compositionupdate": 2,
        },
        "tts_write_request_count": 0,
        "untrusted_event_count": 0,
    }


def _report() -> bytes:
    expected = _expectation()
    captures = []
    base_captures = []
    system_ime = []
    focus_captures = []
    fallback_sentinels = []
    for width, height, mode in FIXED_REQUIRED_CAPTURES:
        screenshot_sha = hashlib.sha256(
            f"{width}x{height}-{mode}".encode()
        ).hexdigest()
        console_sha = hashlib.sha256(f"console-{mode}".encode()).hexdigest()
        page_error_sha = hashlib.sha256(f"page-{mode}".encode()).hexdigest()
        captures.append(
            {
                "assistant_mode": mode,
                "console_count": 0,
                "console_dropped_count": 0,
                "console_summary_sha256": console_sha,
                "device_pixel_ratio": 1,
                "horizontal_overflow_px": 0,
                "nonzero_overlap_pair_count": 0,
                "observed_inner_height": height,
                "observed_inner_width": width,
                "page_error_count": 0,
                "page_error_dropped_count": 0,
                "page_error_summary_sha256": page_error_sha,
                "screenshot_bytes": 1234,
                "screenshot_pixel_height": height,
                "screenshot_pixel_width": width,
                "screenshot_sha256": screenshot_sha,
                "target_css_height": height,
                "target_css_width": width,
            }
        )
        base_captures.append(
            {
                "console_summary": {"summary_sha256": console_sha},
                "page_error_summary": {"summary_sha256": page_error_sha},
                "screenshot_bytes": 1234,
                "screenshot_pixel_height": height,
                "screenshot_pixel_width": width,
                "screenshot_sha256": screenshot_sha,
            }
        )
        system_ime.append(
            {
                **_ime("codemirror6"),
                "assistant_mode": mode,
                "target_css_height": height,
                "target_css_width": width,
            }
        )
        focus_captures.append(
            {
                "all_control_names_nonempty": True,
                "all_controls_keyboard_reachable": True,
                "assistant_mode": mode,
                "control_count": 7,
                "target_css_height": height,
                "target_css_width": width,
            }
        )
        fallback_sentinels.append(
            {
                "assistant_mode": mode,
                "code_mirror_absent": True,
                "focus_aria": {
                    "all_control_names_nonempty": True,
                    "all_controls_keyboard_reachable": True,
                    "control_count": 7,
                },
                "observed_inner_height": height,
                "observed_inner_width": width,
                "target_css_height": height,
                "target_css_width": width,
                "textarea_visible": True,
            }
        )
    browser_identity = {"fixed": True}
    route_evidence = {"route_kind": "chat_root"}
    unsigned = {
        "base_observation": {
            "browser_identity": browser_identity,
            "captures": base_captures,
            "route_evidence": route_evidence,
        },
        "browser_identity": browser_identity,
        "captures": captures,
        "chapter_switch": {
            "generation_a": 1,
            "generation_b": 2,
            "generation_return": 3,
            "player_a_inactive_on_b": True,
            "primary_edition_id_sha256": "1" * 64,
            "restored_same_edition": True,
            "stale_primary_action_count": 0,
            "status": "observed",
        },
        "controller_id": SUPPLEMENT_CONTROLLER_ID,
        "fixture_manifest_sha256": expected.fixture_manifest_sha256,
        "focus_aria": {
            "all_control_names_nonempty": True,
            "all_visible_enabled_controls_keyboard_reachable": True,
            "captures": focus_captures,
            "context_menu_focus_observed": True,
            "editor_focus_restored": True,
            "focus_visible_style_observed": True,
            "live_region_polite": True,
            "review": {
                "aria_references_exist": True,
                "dialog_focus_observed": True,
                "trigger_focus_restored": True,
            },
            "visible_enabled_control_count": 7,
        },
        "novel_id": expected.novel_id,
        "old_draft_update": {
            "automatic_tts_write_count": 0,
            "baseline_edition_unchanged": True,
            "controlled_update_response_status": 503,
            "draft_write_count": 2,
            "explicit_update_intent": "update",
            "gutter_update_required_observed": True,
            "old_audio_remained_available": True,
            "old_draft_marker_visible": True,
            "source_restored": True,
            "status": "observed",
            "synthesis_completed_claimed": False,
        },
        "primary_document_id": expected.primary_document_id,
        "progress_lifecycle": {
            "baseline_projection_sha256": "2" * 64,
            "close_reopen_restored": True,
            "edition_id_sha256": "3" * 64,
            "offset_tolerance_ms": 1500,
            "progress_put_observed": True,
            "reload_restored": True,
            "restored_projection_sha256": "4" * 64,
            "status": "observed",
        },
        "recovery": {
            "baseline_source_sha256": expected.baseline_source_sha256,
            "final_source_sha256": expected.baseline_source_sha256,
            "status": "restored",
        },
        "request_fingerprint_sha256": expected.request_fingerprint_sha256,
        "route_evidence": route_evidence,
        "schema_version": SUPPLEMENT_REPORT_SCHEMA,
        "secondary_document_id": expected.secondary_document_id,
        "supplement_run_id": expected.supplement_run_id,
        "system_ime": system_ime,
        "target_scope_sha256": expected.target_scope_sha256,
        "textarea_fallback": {
            "accessible_name_nonempty": True,
            "audio_playable": True,
            "code_mirror_absent": True,
            "fault_injection_count": 1,
            "fault_injection_id": TEXTAREA_FAULT_INJECTION_ID,
            "gutter_count": 0,
            "ime": _ime("textarea-fallback"),
            "sentinels": fallback_sentinels,
            "status": "observed",
            "textarea_visible": True,
        },
    }
    report = {
        **unsigned,
        "report_sha256": hashlib.sha256(_canonical(unsigned)).hexdigest(),
    }
    return _canonical(report) + b"\n"


def test_request_is_canonical_and_base_run_binding_is_deterministic() -> None:
    expected = _expectation()
    value = json.loads(_canonical_request(expected))
    assert value["supplement_run_id"] == expected.supplement_run_id
    assert value["primary_document_id"] == expected.primary_document_id
    assert "validation_token" not in value
    assert len(_base_run_fingerprint(expected)) == 64


def test_strict_report_accepts_all_fixed_evidence_and_delegates_base() -> None:
    seen: list[tuple[bytes, object]] = []
    base_value = object()

    def parse_base(raw: bytes, expectation: object) -> object:
        seen.append((raw, expectation))
        return base_value

    verified = _parse_browser_supplement_report(
        _report(), _expectation(), parse_base=parse_base
    )
    assert verified.base_observation is base_value
    assert verified.system_ime_capture_count == 4
    assert verified.textarea_fallback_observed is True
    assert verified.recovery_status == "restored"
    assert json.loads(seen[0][0])["browser_identity"] == {"fixed": True}
    assert seen[0][1].run_fingerprint_sha256 == _base_run_fingerprint(
        _expectation()
    )


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        (("system_ime", 0, "operator_confirmed"), False),
        (("system_ime", 1, "trusted_counts", "compositionupdate"), 0),
        (("textarea_fallback", "fault_injection_count"), 2),
        (("focus_aria", "review", "trigger_focus_restored"), False),
        (("progress_lifecycle", "reload_restored"), False),
        (("chapter_switch", "generation_b"), 1),
        (("old_draft_update", "synthesis_completed_claimed"), True),
        (("recovery", "status"), "failed"),
    ],
)
def test_report_fails_closed_for_each_supplemental_gate(
    mutation: tuple[object, ...], value: object
) -> None:
    report = json.loads(_report())
    target = report
    for key in mutation[:-1]:
        target = target[key]
    target[mutation[-1]] = value
    unsigned = {key: item for key, item in report.items() if key != "report_sha256"}
    report["report_sha256"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
    with pytest.raises(BrowserSupplementError) as caught:
        _parse_browser_supplement_report(
            _canonical(report) + b"\n",
            _expectation(),
            parse_base=lambda _raw, _expectation: object(),
        )
    assert caught.value.code == "BROWSER_SUPPLEMENT_REPORT_INVALID"


def test_hold_keeps_manual_checkpoint_and_recovery_status_machine_readable() -> None:
    error = _parse_hold(
        _canonical(
            {
                "error_code": "SYSTEM_IME_OPERATOR_INPUT_REQUIRED",
                "recovery_status": "restored",
                "status": "hold",
            }
        )
        + b"\n"
    )
    assert error.code == "SYSTEM_IME_OPERATOR_INPUT_REQUIRED"
    assert error.recovery_status == "restored"
    malformed = _parse_hold(b'{"status":"hold","secret":"raw"}\n')
    assert malformed.code == "BROWSER_SUPPLEMENT_EXECUTION_HOLD"
