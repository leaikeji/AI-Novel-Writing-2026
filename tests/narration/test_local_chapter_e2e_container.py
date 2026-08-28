from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import types

import pytest

from scripts.tts import local_chapter_e2e_container as helper
from scripts.tts import chapter_e2e_collector as real_collector


RUN_ID = "11111111-2222-4333-8444-555555555555"
NOVEL_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DOCUMENT_ID = "01234567-89ab-4cde-8fab-0123456789ab"


def test_sealed_bundle_includes_listening_finalizer_exactly_once() -> None:
    assert "scripts/tts/chapter_e2e_listening.py" in helper.BUNDLE_RELATIVE_PATHS
    assert helper.FIXTURE_RELATIVE_PATH == (
        "tests/fixtures/narration/chapter-e2e-v3.json"
    )
    assert helper.FIXTURE_RELATIVE_PATH in helper.BUNDLE_RELATIVE_PATHS
    assert len(helper.BUNDLE_RELATIVE_PATHS) == len(set(helper.BUNDLE_RELATIVE_PATHS))
REQUEST_SHA = "1" * 64


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_bytes(data)
    path.chmod(0o600)


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    secret = tmp_path / "secret"
    secret.mkdir(mode=0o700, parents=True)
    runs = secret / "t4k-runs"
    runs.mkdir(mode=0o700)
    root = runs / RUN_ID
    root.mkdir(mode=0o700)
    tool = root / "tool"
    tool.mkdir(mode=0o700)
    backend = tmp_path / "installed" / "backend"
    backend.mkdir(mode=0o700, parents=True)
    (backend / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    monkeypatch.setattr(helper, "SECRET_PROJECT_ROOT", secret)
    monkeypatch.setattr(helper, "RUNS_ROOT", runs)
    monkeypatch.setattr(helper, "INSTALLED_PLUGIN_ROOT", backend.parent)
    monkeypatch.setattr(
        helper,
        "__file__",
        str(tool / "scripts/tts/local_chapter_e2e_container.py"),
    )
    files: dict[str, str] = {}
    for index, relative in enumerate(helper.BUNDLE_RELATIVE_PATHS):
        data = f"bundle-{index}-{relative}\n".encode()
        path = tool / relative
        _write_private(path, data)
        files[relative] = hashlib.sha256(data).hexdigest()
    for directory in sorted(
        (path for path in tool.rglob("*") if path.is_dir()),
        key=lambda value: len(value.parts),
    ):
        directory.chmod(0o700)
    unsigned = {
        "schema_version": helper.BUNDLE_SCHEMA_VERSION,
        "files": files,
        "backend_tree_sha256": helper._python_tree_sha256(backend),
    }
    manifest = {
        **unsigned,
        "bundle_sha256": hashlib.sha256(
            helper._canonical_json_bytes(unsigned)
        ).hexdigest(),
    }
    _write_private(
        tool / helper.BUNDLE_MANIFEST_NAME,
        helper._canonical_json_bytes(manifest),
    )
    return helper._run_paths(RUN_ID), root, tool


def _refresh_bundle_manifest(tool: Path) -> None:
    manifest_path = tool / helper.BUNDLE_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = {
        relative: hashlib.sha256((tool / relative).read_bytes()).hexdigest()
        for relative in helper.BUNDLE_RELATIVE_PATHS
    }
    unsigned = {
        "schema_version": helper.BUNDLE_SCHEMA_VERSION,
        "files": files,
        "backend_tree_sha256": manifest["backend_tree_sha256"],
    }
    _write_private(
        manifest_path,
        helper._canonical_json_bytes(
            {
                **unsigned,
                "bundle_sha256": hashlib.sha256(
                    helper._canonical_json_bytes(unsigned)
                ).hexdigest(),
            }
        ),
    )


def test_stop_launcher_signals_only_the_exact_run_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    paths["recovery"].mkdir(mode=0o700)
    paths["result"].mkdir(mode=0o700)
    proc = tmp_path / "proc"
    exact = proc / "123"
    foreign = proc / "456"
    exact.mkdir(mode=0o700, parents=True)
    foreign.mkdir(mode=0o700)

    def cmdline(document_id: str) -> bytes:
        return b"\x00".join(
            item.encode("utf-8")
            for item in (
                "/app/venv/bin/python",
                "-B",
                str(paths["tool"] / "scripts/tts/run_chapter_e2e_real.py"),
                "--mode",
                "real",
                "--run-id",
                RUN_ID,
                "--novel-id",
                NOVEL_ID,
                "--document-id",
                document_id,
                "--private-work-dir",
                str(paths["recovery"]),
                "--output-dir",
                str(paths["result"]),
            )
        ) + b"\x00"

    (exact / "cmdline").write_bytes(cmdline(DOCUMENT_ID))
    (foreign / "cmdline").write_bytes(cmdline(str("f" * 8 + DOCUMENT_ID[8:])))
    signals: list[tuple[int, int]] = []

    def kill(pid: int, stop_signal: int) -> None:
        signals.append((pid, stop_signal))
        (exact / "cmdline").unlink()
        exact.rmdir()

    monkeypatch.setattr(helper.os, "kill", kill)

    helper._stop_launcher(  # noqa: SLF001
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        proc_root=proc,
        sleeper=lambda _seconds: None,
    )

    assert signals == [(123, helper.signal.SIGINT)]
    assert foreign.exists()


def test_stop_launcher_waits_sixty_seconds_before_escalating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    paths["recovery"].mkdir(mode=0o700)
    paths["result"].mkdir(mode=0o700)
    proc = tmp_path / "proc"
    exact = proc / "123"
    exact.mkdir(mode=0o700, parents=True)
    (exact / "cmdline").write_bytes(
        b"\x00".join(
            item.encode("utf-8")
            for item in (
                "/app/venv/bin/python",
                "-B",
                str(paths["tool"] / "scripts/tts/run_chapter_e2e_real.py"),
                "--mode",
                "real",
                "--run-id",
                RUN_ID,
                "--novel-id",
                NOVEL_ID,
                "--document-id",
                DOCUMENT_ID,
                "--private-work-dir",
                str(paths["recovery"]),
                "--output-dir",
                str(paths["result"]),
            )
        )
        + b"\x00"
    )
    signals: list[tuple[int, int]] = []
    sleeps: list[float] = []

    def kill(pid: int, stop_signal: int) -> None:
        signals.append((pid, stop_signal))
        if stop_signal == helper.signal.SIGTERM:
            (exact / "cmdline").unlink()
            exact.rmdir()

    monkeypatch.setattr(helper.os, "kill", kill)

    helper._stop_launcher(  # noqa: SLF001
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        proc_root=proc,
        sleeper=sleeps.append,
    )

    assert signals == [
        (123, helper.signal.SIGINT),
        (123, helper.signal.SIGTERM),
    ]
    assert sleeps == [0.1] * 600


def _result_payload(
    paths: dict[str, Path],
    *,
    status: str = "PASS_CANDIDATE",
    evidence_root: str = "e" * 64,
) -> dict[str, object]:
    return {
        "schema_version": helper.RESULT_SCHEMA_VERSION,
        "work_package": helper.WORK_PACKAGE,
        "run_fingerprint_sha256": helper._sha256_text(RUN_ID),
        "created_at": "2026-08-27T00:00:00Z",
        "mode": "real",
        "status": status,
        "fixture": {
            "manifest_sha256": helper._hash_file(
                paths["tool"] / helper.FIXTURE_RELATIVE_PATH
            )
        },
        "target_scope_sha256": helper._sha256_text(
            f"{NOVEL_ID}:{DOCUMENT_ID}"
        ),
        "api": {"loopback_only": True},
        "duration_minutes": 30.0,
        "required_viewports": [],
        "safety": {
            "no_secrets_recorded": True,
            "no_private_paths_recorded": True,
        },
        "automatic_chain": {
            "state": "PASS",
            "edition_id_sha256": "a" * 64,
            "edition_fingerprint_sha256": "b" * 64,
        },
        "manual_chain": {
            "state": "PASS",
            "edition_id_sha256": "c" * 64,
            "edition_fingerprint_sha256": "d" * 64,
        },
        "technical_checks": {
            "state": "PASS",
            "stability_elapsed_seconds": 1800.0,
            "chapter_audio_duration_seconds": 100.0,
            "request_to_ready_seconds": 42.0,
            "black_box_rtf": 0.42,
            "performance_gate": {
                "black_box_rtf_limit": 1.0,
                "black_box_rtf_passed": True,
                "progressive_playback_alternative": (
                    "not_eligible_without_strict_ready_window_evidence"
                ),
                "host_paging_observed": False,
                "host_paging_interpretation": "whole_host_telemetry_only",
                "pageout_delta": 0,
                "swapout_delta": 0,
                "memory_baseline_median_bytes": 1_800_000_000,
                "memory_tail_median_bytes": 1_900_000_000,
                "memory_growth_bytes": 100_000_000,
                "memory_growth_limit_bytes": 134_217_728,
                "sidecar_memory_growth_observed": False,
                "qwenpaw_slowdown_observed": False,
                "sidecar_peak_memory_limit_bytes": 4 * 1024 * 1024 * 1024,
                "memory_safety_passed": True,
            },
            "time_to_first_audio_ms": 1200,
            "peak_memory_bytes": 2_000_000_000,
            "range_status_codes": [200, 206, 304, 416],
            "seam_pairs_checked": 3,
            "seek_latest_wins": True,
            "pending_gap_not_skipped": True,
            "edit_actions_created_tts_writes": 0,
            "evidence_class": "local_operator_observation",
            "evidence_root_sha256": evidence_root,
            "browser_viewports": [
                {"width": 1920, "height": 1080},
                {"width": 2560, "height": 1440},
            ],
            "browser_assistant_modes": ["collapsed", "expanded"],
            "browser_console_error_count": 0,
            "browser_overlap_count": 0,
            "sidecar_restart_count": 0,
            "health_failure_count": 0,
            "listening_output_hashes": ["a" * 64],
            "collector_collected_at": "2026-08-27T00:00:00Z",
            "rtf_kind": "request_to_ready_black_box",
        },
        "human_listening": {"state": "PASS"},
        "recovery": {
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "recovery_required": False,
        },
        "error_codes": [],
    }


@pytest.mark.parametrize(
    ("target", "key", "value"),
    (
        ("technical", "peak_memory_bytes", 4 * 1024 * 1024 * 1024 + 1),
        ("performance", "sidecar_memory_growth_observed", True),
        ("performance", "qwenpaw_slowdown_observed", True),
        ("performance", "pageout_delta", None),
        ("performance", "memory_growth_bytes", True),
        ("performance", "memory_growth_limit_bytes", 134_217_729),
        (
            "performance",
            "memory_baseline_median_bytes",
            2_000_000_001,
        ),
        ("performance", "memory_tail_median_bytes", 2_000_000_001),
        ("performance", "host_paging_observed", 0),
    ),
)
def test_technical_memory_gate_rejects_invalid_or_failed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    key: str,
    value: object,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    technical = _result_payload(paths)["technical_checks"]
    assert type(technical) is dict
    destination = (
        technical
        if target == "technical"
        else technical["performance_gate"]
    )
    assert type(destination) is dict
    destination[key] = value

    with pytest.raises(helper.ContainerHelperError, match="RESULT_INVALID"):
        helper._validate_technical_memory_gate(technical)


def test_prepare_creates_exact_private_layout_locks_and_voice_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    for key in ("recovery", "result", "listening", "incoming"):
        assert (paths[key].stat().st_mode & 0o777) == 0o700
    for name in ("lock-nano", "lock-browser", "lock-data"):
        path = paths["recovery"] / name
        assert path.read_bytes() == b""
        assert (path.stat().st_mode & 0o777) == 0o600
    attestation = json.loads(
        (paths["recovery"] / "readiness-attestation.json").read_text()
    )
    assert attestation["novel_id"] == NOVEL_ID
    assert attestation["document_id"] == DOCUMENT_ID
    assert attestation["expected_characters"] == ["林晚", "沈川"]
    assert [
        (row["role"], row["preset_id"])
        for row in attestation["expected_official_presets"]
    ] == list(helper.EXPECTED_VOICES)
    assert [
        (row["width"], row["height"], row["assistant_mode"])
        for row in attestation["required_captures"]
    ] == list(helper.EXPECTED_CAPTURES)
    assert all(
        Path(row["path"]).parent == paths["recovery"]
        for row in attestation["resource_locks"]
    )


def test_bundle_verifier_rejects_changed_source_and_installed_backend_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    helper._load_and_verify_bundle(paths)
    changed = tool / helper.BUNDLE_RELATIVE_PATHS[0]
    changed.write_text("changed\n", encoding="utf-8")
    with pytest.raises(helper.ContainerHelperError, match="BUNDLE_INVALID"):
        helper._load_and_verify_bundle(paths)

    paths, _root, _tool = _fixture(tmp_path / "second", monkeypatch)
    backend = helper.INSTALLED_PLUGIN_ROOT / "backend"
    (backend / "app.py").write_text("DRIFT = True\n", encoding="utf-8")
    with pytest.raises(helper.ContainerHelperError, match="BACKEND_DRIFT"):
        helper._load_and_verify_bundle(paths)


def test_partial_ready_capability_requires_exact_staged_launcher_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    with pytest.raises(
        helper.ContainerHelperError,
        match="PARTIAL_READY_LAUNCHER_REQUIRED",
    ):
        helper._require_partial_ready_launcher_capability(paths)

    launcher = tool / "scripts/tts/run_chapter_e2e_real.py"
    _write_private(
        launcher,
        (
            "T4K_PARTIAL_READY_VALIDATION_CAPABILITY = "
            f"{helper.PARTIAL_READY_LAUNCHER_CAPABILITY!r}\n"
        ).encode("utf-8"),
    )
    _refresh_bundle_manifest(tool)
    helper._require_partial_ready_launcher_capability(paths)


def test_claim_gate_uses_only_fixed_loopback_path_body_and_redacts_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class Response:
        status = 200

        def read(self, amount: int) -> bytes:
            assert amount == helper._MAX_JSON_BYTES + 1
            return helper._canonical_json_bytes(
                {
                    "code": "VALIDATION_SEGMENT_CLAIM_GATE_ARMED",
                    "state": "armed",
                    "claim_limit": 1,
                    "claimed_count": 0,
                    "remaining_count": 1,
                    "expires_at": "2026-08-27T00:00:00Z",
                    "run_fingerprint_sha256": hashlib.sha256(
                        b"narration-validation-claim-gate-run/1\x00"
                        + RUN_ID.encode("ascii")
                    ).hexdigest(),
                    "scope_fingerprint_sha256": hashlib.sha256(
                        b"narration-validation-claim-gate-scope/1\x00"
                        + NOVEL_ID.encode("ascii")
                        + b"\x00"
                        + DOCUMENT_ID.encode("ascii")
                    ).hexdigest(),
                }
            )

    class Connection:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            calls.append(("connect", host, port, timeout))

        def request(self, method, path, *, body, headers):  # type: ignore[no-untyped-def]
            calls.append(("request", method, path, body, headers))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            calls.append(("close",))

    monkeypatch.setattr(helper, "_read_validation_token", lambda: "v" * 43)
    monkeypatch.setattr(helper.http.client, "HTTPConnection", Connection)

    helper._claim_gate_request(
        action="arm",
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )

    assert calls[0] == ("connect", "127.0.0.1", 8088, 15)
    request = calls[1]
    assert request[0:2] == ("request", "POST")
    assert request[2] == (
        "/api/ai-novel-world-2026"
        f"/novels/{NOVEL_ID}/documents/{DOCUMENT_ID}"
        "/narration-validation-segment-claim-gate"
    )
    assert json.loads(request[3]) == {
        "run_id": RUN_ID,
        "segment_claim_limit": 1,
        "ttl_seconds": 120,
    }
    assert request[4][helper.VALIDATION_TOKEN_HEADER] == "v" * 43
    assert "v" * 43 not in str(request[2])
    assert "v" * 43 not in bytes(request[3]).decode("utf-8")


def _host_marker(collector_raw: bytes, probe_raw: bytes) -> bytes:
    unsigned = {
        "schema_version": "moss-tts-chapter-e2e-local-operator-commit/1.0",
        "request_fingerprint_sha256": REQUEST_SHA,
        "collector": {
            "filename": "collector-report.json",
            "sha256": hashlib.sha256(collector_raw).hexdigest(),
            "file_identity_sha256": "a" * 64,
        },
        "probe": {
            "filename": "probe-report.json",
            "sha256": hashlib.sha256(probe_raw).hexdigest(),
            "file_identity_sha256": "b" * 64,
        },
    }
    return helper._canonical_json_bytes(
        {
            **unsigned,
            "pair_commit_fingerprint_sha256": hashlib.sha256(
                helper._canonical_json_payload_bytes(unsigned)
            ).hexdigest(),
        }
    )


@pytest.mark.parametrize("fingerprint_includes_file_newline", [False, True])
def test_report_import_uses_canonical_host_marker_fingerprint_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fingerprint_includes_file_newline: bool,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    for key in ("recovery", "result", "listening", "incoming"):
        paths[key].mkdir(mode=0o700)
    _write_private(paths["recovery"] / "probe-request.json", b"{}\n")
    collector_raw = b'{"collector":true}\n'
    probe_raw = b'{"probe":true}\n'
    marker_raw = real_collector._build_local_operator_commit_marker(
        request_fingerprint_sha256=REQUEST_SHA,
        collector_bytes=collector_raw,
        collector_identity=(1, 2, 3, 4, 5, 6),
        probe_bytes=probe_raw,
        probe_identity=(7, 8, 9, 10, 11, 12),
    )
    marker = json.loads(marker_raw)
    unsigned = dict(marker)
    fingerprint = unsigned.pop("pair_commit_fingerprint_sha256")
    canonical_unsigned = helper._canonical_json_payload_bytes(unsigned)

    assert marker_raw == helper._canonical_json_bytes(marker)
    assert marker_raw.endswith(b"\n")
    assert not canonical_unsigned.endswith(b"\n")
    assert fingerprint == hashlib.sha256(canonical_unsigned).hexdigest()
    assert fingerprint != hashlib.sha256(canonical_unsigned + b"\n").hexdigest()

    if fingerprint_includes_file_newline:
        marker["pair_commit_fingerprint_sha256"] = hashlib.sha256(
            canonical_unsigned + b"\n"
        ).hexdigest()
        marker_raw = helper._canonical_json_bytes(marker)

    _write_private(paths["incoming"] / "collector-report.json", collector_raw)
    _write_private(paths["incoming"] / "probe-report.json", probe_raw)
    _write_private(
        paths["incoming"] / "collector-report.commit.json",
        marker_raw,
    )

    request = types.SimpleNamespace(
        expectation=object(),
        request_fingerprint_sha256=REQUEST_SHA,
    )
    published: list[str] = []
    fake = types.ModuleType("scripts.tts.chapter_e2e_collector")
    fake._load_request = lambda *_args, **_kwargs: (
        request,
        paths["recovery"],
        (1, 2, 3),
    )
    fake._validate_local_operator_collector_candidate = (
        lambda **_kwargs: (REQUEST_SHA, object())
    )

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield 99

    fake._collector_transaction_lock = transaction
    fake._ensure_outputs_absent = lambda *_args: None

    def publish(_fd, *, filename, data):  # type: ignore[no-untyped-def]
        del data
        published.append(filename)
        return (len(published),) * 8

    fake._publish_exact_file = publish
    fake._build_local_operator_commit_marker = (
        real_collector._build_local_operator_commit_marker
    )
    fake._assert_parent_identity = lambda *_args: None
    monkeypatch.setitem(sys.modules, "scripts.tts.chapter_e2e_collector", fake)
    import scripts.tts as tts_package

    monkeypatch.setattr(tts_package, "chapter_e2e_collector", fake, raising=False)

    if fingerprint_includes_file_newline:
        with pytest.raises(helper.ContainerHelperError, match="REPORT_INVALID"):
            helper._import_report(paths)
        assert published == []
        return

    helper._import_report(paths)
    assert published == [
        "collector-report.json",
        "probe-report.json",
        "collector-report.commit.json",
    ]


def test_report_import_validates_host_pair_and_publishes_container_commit_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    for key in ("recovery", "result", "listening", "incoming"):
        paths[key].mkdir(mode=0o700)
    _write_private(paths["recovery"] / "probe-request.json", b"{}\n")
    collector_raw = b'{"collector":true}\n'
    probe_raw = b'{"probe":true}\n'
    _write_private(paths["incoming"] / "collector-report.json", collector_raw)
    _write_private(paths["incoming"] / "probe-report.json", probe_raw)
    _write_private(
        paths["incoming"] / "collector-report.commit.json",
        _host_marker(collector_raw, probe_raw),
    )

    expectation = object()
    request = types.SimpleNamespace(
        expectation=expectation,
        request_fingerprint_sha256=REQUEST_SHA,
    )
    published: list[str] = []
    fake = types.ModuleType("scripts.tts.chapter_e2e_collector")
    fake._load_request = lambda *_args, **_kwargs: (
        request,
        paths["recovery"],
        (1, 2, 3),
    )
    fake._validate_local_operator_collector_candidate = (
        lambda **_kwargs: (REQUEST_SHA, object())
    )

    @contextmanager
    def transaction(*_args, **_kwargs):
        yield 99

    fake._collector_transaction_lock = transaction
    fake._ensure_outputs_absent = lambda *_args: None

    def publish(_fd, *, filename, data):  # type: ignore[no-untyped-def]
        del data
        published.append(filename)
        return (len(published),) * 8

    fake._publish_exact_file = publish
    fake._build_local_operator_commit_marker = lambda **_kwargs: b"{}\n"
    fake._assert_parent_identity = lambda *_args: None
    monkeypatch.setitem(sys.modules, "scripts.tts.chapter_e2e_collector", fake)
    import scripts.tts as tts_package

    monkeypatch.setattr(tts_package, "chapter_e2e_collector", fake, raising=False)

    helper._import_report(paths)
    assert published == [
        "collector-report.json",
        "probe-report.json",
        "collector-report.commit.json",
    ]


def test_report_import_rejects_foreign_host_marker_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    for key in ("recovery", "result", "listening", "incoming"):
        paths[key].mkdir(mode=0o700)
    _write_private(paths["recovery"] / "probe-request.json", b"{}\n")
    collector_raw = b'{"collector":true}\n'
    probe_raw = b'{"probe":true}\n'
    marker = json.loads(_host_marker(collector_raw, probe_raw))
    marker["collector"]["sha256"] = "f" * 64
    _write_private(paths["incoming"] / "collector-report.json", collector_raw)
    _write_private(paths["incoming"] / "probe-report.json", probe_raw)
    _write_private(
        paths["incoming"] / "collector-report.commit.json",
        helper._canonical_json_bytes(marker),
    )
    request = types.SimpleNamespace(
        expectation=object(),
        request_fingerprint_sha256=REQUEST_SHA,
    )
    fake = types.ModuleType("scripts.tts.chapter_e2e_collector")
    fake._load_request = lambda *_args, **_kwargs: (
        request,
        paths["recovery"],
        (1, 2, 3),
    )
    fake._validate_local_operator_collector_candidate = (
        lambda **_kwargs: (REQUEST_SHA, object())
    )
    monkeypatch.setitem(sys.modules, "scripts.tts.chapter_e2e_collector", fake)
    import scripts.tts as tts_package

    monkeypatch.setattr(tts_package, "chapter_e2e_collector", fake, raising=False)
    with pytest.raises(helper.ContainerHelperError, match="REPORT_INVALID"):
        helper._import_report(paths)


@pytest.mark.parametrize("fail_after", [1, 2])
def test_report_import_retries_an_interrupted_identical_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_after: int,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    for key in ("recovery", "result", "listening", "incoming"):
        paths[key].mkdir(mode=0o700)
    _write_private(paths["recovery"] / "probe-request.json", b"{}\n")
    collector_raw = b'{"collector":true}\n'
    probe_raw = b'{"probe":true}\n'
    _write_private(paths["incoming"] / "collector-report.json", collector_raw)
    _write_private(paths["incoming"] / "probe-report.json", probe_raw)
    _write_private(
        paths["incoming"] / "collector-report.commit.json",
        _host_marker(collector_raw, probe_raw),
    )

    expectation = object()
    request = types.SimpleNamespace(
        expectation=expectation,
        request_fingerprint_sha256=REQUEST_SHA,
    )
    fake = types.ModuleType("scripts.tts.chapter_e2e_collector")
    fake._load_request = lambda *_args, **_kwargs: (
        request,
        paths["recovery"],
        real_collector._directory_identity(paths["recovery"].stat()),
    )
    fake._validate_local_operator_collector_candidate = (
        lambda **_kwargs: (REQUEST_SHA, object())
    )
    fake._collector_transaction_lock = real_collector._collector_transaction_lock
    fake._ensure_outputs_absent = real_collector._ensure_outputs_absent
    publish_calls = 0

    def interrupted_publish(fd, *, filename, data):  # type: ignore[no-untyped-def]
        nonlocal publish_calls
        identity = real_collector._publish_exact_file(
            fd,
            filename=filename,
            data=data,
        )
        publish_calls += 1
        if publish_calls == fail_after:
            raise OSError("injected interruption")
        return identity

    fake._publish_exact_file = interrupted_publish
    fake._build_local_operator_commit_marker = (
        real_collector._build_local_operator_commit_marker
    )
    fake._assert_parent_identity = real_collector._assert_parent_identity
    monkeypatch.setitem(sys.modules, "scripts.tts.chapter_e2e_collector", fake)
    import scripts.tts as tts_package

    monkeypatch.setattr(tts_package, "chapter_e2e_collector", fake, raising=False)
    with pytest.raises(helper.ContainerHelperError, match="REPORT_INVALID"):
        helper._import_report(paths)
    assert (paths["recovery"] / "collector-report.json").read_bytes() == collector_raw
    assert (paths["recovery"] / "probe-report.json").exists() is (fail_after == 2)
    assert not (paths["recovery"] / "collector-report.commit.json").exists()

    fake._publish_exact_file = real_collector._publish_exact_file
    helper._import_report(paths)
    assert all((paths["recovery"] / name).is_file() for name in helper.REPORT_FILENAMES)
    marker = json.loads(
        (paths["recovery"] / "collector-report.commit.json").read_text()
    )
    assert marker["collector"]["sha256"] == hashlib.sha256(collector_raw).hexdigest()
    assert marker["probe"]["sha256"] == hashlib.sha256(probe_raw).hexdigest()


def test_status_rejects_result_from_foreign_run_or_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    result = _result_payload(paths)
    result["run_fingerprint_sha256"] = "f" * 64
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(result),
    )
    monkeypatch.setattr(
        helper,
        "_load_verified_operator_evidence_root",
        lambda _paths: "e" * 64,
    )
    with pytest.raises(helper.ContainerHelperError, match="RESULT_INVALID"):
        helper._status(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
        )


def _recovery_payload(
    paths: dict[str, Path],
    *,
    schema_version: str,
    baseline_restored: bool,
    restoration_evidence: object = None,
    include_restoration_evidence: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "work_package": helper.WORK_PACKAGE,
        "run_id": RUN_ID,
        "novel_id": NOVEL_ID,
        "document_id": DOCUMENT_ID,
        "state": "LISTENING_PENDING",
        "baseline_restored": baseline_restored,
        "fixture": {
            "manifest_sha256": helper._hash_file(
                paths["tool"] / helper.FIXTURE_RELATIVE_PATH
            )
        },
    }
    if include_restoration_evidence:
        payload["restoration_evidence"] = restoration_evidence
    payload["self_sha256"] = hashlib.sha256(
        helper._canonical_json_payload_bytes(payload)
    ).hexdigest()
    return payload


def test_recovery_31_binding_requires_exact_restoration_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    payload = _recovery_payload(
        paths,
        schema_version=helper.RECOVERY_SCHEMA_VERSION,
        baseline_restored=True,
        include_restoration_evidence=True,
        restoration_evidence={
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "new_authoritative_record_count": 3,
        },
    )
    _write_private(
        paths["recovery"] / "recovery.json",
        helper._canonical_json_bytes(payload),
    )

    helper._validate_recovery_binding(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        fixture_sha256=payload["fixture"]["manifest_sha256"],  # type: ignore[index]
        expected_state="LISTENING_PENDING",
        require_baseline_restored=True,
    )


@pytest.mark.parametrize(
    "restoration_evidence",
    (
        None,
        {
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
        },
        {
            "working_copy_content_restored": False,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "new_authoritative_record_count": 3,
        },
        {
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "new_authoritative_record_count": True,
        },
        {
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "new_authoritative_record_count": -1,
        },
    ),
)
def test_recovery_31_binding_rejects_missing_or_invalid_restoration_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restoration_evidence: object,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    payload = _recovery_payload(
        paths,
        schema_version=helper.RECOVERY_SCHEMA_VERSION,
        baseline_restored=True,
        include_restoration_evidence=restoration_evidence is not None,
        restoration_evidence=restoration_evidence,
    )
    _write_private(
        paths["recovery"] / "recovery.json",
        helper._canonical_json_bytes(payload),
    )

    with pytest.raises(helper.ContainerHelperError, match="RESULT_INVALID"):
        helper._validate_recovery_binding(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
            fixture_sha256=payload["fixture"]["manifest_sha256"],  # type: ignore[index]
            expected_state="LISTENING_PENDING",
            require_baseline_restored=True,
        )


def test_recovery_30_binding_remains_readable_but_rejects_31_only_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    payload = _recovery_payload(
        paths,
        schema_version=helper.LEGACY_RECOVERY_SCHEMA_VERSION,
        baseline_restored=True,
    )
    recovery_path = paths["recovery"] / "recovery.json"
    _write_private(recovery_path, helper._canonical_json_bytes(payload))
    fixture_sha256 = payload["fixture"]["manifest_sha256"]  # type: ignore[index]

    helper._validate_recovery_binding(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        fixture_sha256=fixture_sha256,
        expected_state="LISTENING_PENDING",
        require_baseline_restored=True,
    )

    payload = _recovery_payload(
        paths,
        schema_version=helper.LEGACY_RECOVERY_SCHEMA_VERSION,
        baseline_restored=True,
        include_restoration_evidence=True,
        restoration_evidence={
            "working_copy_content_restored": True,
            "author_visible_edition_restored": True,
            "append_only_history_retained": True,
            "new_authoritative_record_count": 3,
        },
    )
    recovery_path.unlink()
    _write_private(recovery_path, helper._canonical_json_bytes(payload))
    with pytest.raises(helper.ContainerHelperError, match="RESULT_INVALID"):
        helper._validate_recovery_binding(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
            fixture_sha256=fixture_sha256,
            expected_state="LISTENING_PENDING",
            require_baseline_restored=True,
        )


@pytest.mark.parametrize(
    ("error_codes", "expected_status"),
    (
        (["HUMAN_LISTENING_FAILED"], "HUMAN_LISTENING_FAILED"),
        ([], "FAILED"),
        (["HUMAN_LISTENING_FAILED", "OTHER_FAILURE"], "FAILED"),
        (["OTHER_FAILURE"], "FAILED"),
    ),
)
def test_status_maps_only_exact_bound_human_listening_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_codes: list[str],
    expected_status: str,
) -> None:
    paths, _root, _tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    result = _result_payload(paths, status="FAILED")
    result["human_listening"] = {"state": "FAIL"}
    result["error_codes"] = error_codes
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(result),
    )

    assert helper._status(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    ) == expected_status


def test_cleanup_removes_only_tool_and_incoming_after_final_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, root, tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    evidence_root = "e" * 64
    monkeypatch.setattr(
        helper,
        "_load_verified_operator_evidence_root",
        lambda _paths: evidence_root,
    )
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(
            _result_payload(paths, evidence_root=evidence_root)
        ),
    )
    _write_private(paths["recovery"] / "evidence.json", b"{}\n")
    for filename in helper.REPORT_FILENAMES:
        _write_private(paths["recovery"] / filename, b"{}\n")
    _write_private(paths["listening"] / "listening.json", b"{}\n")
    _write_private(paths["incoming"] / "transfer.json", b"{}\n")
    token = helper.SECRET_PROJECT_ROOT / "t4k-validation-token"
    _write_private(token, b"v" * 43)
    # Cleanup binds the sealed staged bundle/result, but must not become
    # impossible merely because the installed PawApp was upgraded later.
    (helper.INSTALLED_PLUGIN_ROOT / "backend" / "app.py").write_text(
        "UPGRADED = True\n",
        encoding="utf-8",
    )

    helper._cleanup(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )

    assert not tool.exists()
    assert not paths["incoming"].exists()
    assert root.is_dir()
    assert (paths["recovery"] / "evidence.json").is_file()
    assert (paths["result"] / "result.json").is_file()
    assert (paths["listening"] / "listening.json").is_file()
    assert (paths["recovery"] / "cleanup-state.json").is_file()
    assert token.read_bytes() == b"v" * 43


def test_cleanup_allows_only_finalized_human_listening_quality_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    result = _result_payload(paths, status="FAILED")
    result["error_codes"] = ["HUMAN_LISTENING_FAILED"]
    result["human_listening"] = {"state": "FAIL"}
    result["recovery"] = {
        **result["recovery"],
        "recovery_required": False,
    }
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(result),
    )
    for filename in helper.REPORT_FILENAMES:
        _write_private(paths["recovery"] / filename, b"{}\n")
    monkeypatch.setattr(
        helper,
        "_load_verified_operator_evidence_root",
        lambda _paths: "e" * 64,
    )

    helper._cleanup(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )

    assert not tool.exists()
    assert not paths["incoming"].exists()
    assert (paths["result"] / "result.json").is_file()


@pytest.mark.parametrize(
    ("error_codes", "listening_state", "recovery_required"),
    (
        ([], "FAIL", False),
        (["OTHER_FAILURE"], "FAIL", False),
        (["HUMAN_LISTENING_FAILED", "OTHER_FAILURE"], "FAIL", False),
        (["HUMAN_LISTENING_FAILED"], "PASS", False),
        (["HUMAN_LISTENING_FAILED"], "FAIL", True),
    ),
)
def test_cleanup_rejects_every_other_failed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_codes: list[str],
    listening_state: str,
    recovery_required: bool,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    result = _result_payload(paths, status="FAILED")
    result["error_codes"] = error_codes
    result["human_listening"] = {"state": listening_state}
    result["recovery"] = {
        **result["recovery"],
        "recovery_required": recovery_required,
    }
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(result),
    )
    monkeypatch.setattr(
        helper,
        "_load_verified_operator_evidence_root",
        lambda _paths: "e" * 64,
    )

    with pytest.raises(helper.ContainerHelperError, match="CLEANUP_HOLD"):
        helper._cleanup(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
        )

    assert tool.is_dir()


def test_cleanup_refuses_pending_recovery_and_preserves_everything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    for key in ("recovery", "result", "listening", "incoming"):
        paths[key].mkdir(mode=0o700)
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes({"status": "PASS_CANDIDATE"}),
    )
    _write_private(paths["recovery"] / "recovery.json", b"{}\n")
    with pytest.raises(helper.ContainerHelperError, match="RECOVERY_PENDING"):
        helper._cleanup(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
        )
    assert tool.is_dir()
    assert paths["incoming"].is_dir()
    assert (paths["recovery"] / "recovery.json").is_file()


def test_cleanup_retries_after_incoming_was_removed_but_tool_delete_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _root, tool = _fixture(tmp_path, monkeypatch)
    helper._prepare(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    _write_private(
        paths["result"] / "result.json",
        helper._canonical_json_bytes(_result_payload(paths)),
    )
    for filename in helper.REPORT_FILENAMES:
        _write_private(paths["recovery"] / filename, b"{}\n")
    monkeypatch.setattr(
        helper,
        "_load_verified_operator_evidence_root",
        lambda _paths: "e" * 64,
    )
    original_rmtree = helper.shutil.rmtree
    failed = False

    def rmtree(path):  # type: ignore[no-untyped-def]
        nonlocal failed
        if Path(path) == tool and not failed:
            failed = True
            raise OSError("injected tool delete failure")
        return original_rmtree(path)

    monkeypatch.setattr(helper.shutil, "rmtree", rmtree)
    with pytest.raises(helper.ContainerHelperError, match="CLEANUP_FAILED"):
        helper._cleanup(
            paths,
            run_id=RUN_ID,
            novel_id=NOVEL_ID,
            document_id=DOCUMENT_ID,
        )
    assert not paths["incoming"].exists()
    assert tool.is_dir()
    assert (paths["recovery"] / "cleanup-state.json").is_file()

    helper._cleanup(
        paths,
        run_id=RUN_ID,
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
    )
    assert not tool.exists()
