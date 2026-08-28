from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from uuid import UUID

import pytest

from scripts.tts.chapter_e2e_executor import TechnicalProbeContext
from scripts.tts.chapter_e2e_probe_request import (
    PROBE_REQUEST_FILENAME,
    PROBE_REQUEST_SCHEMA_VERSION,
    PrivateProbeRequestPublisher,
)
from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    BoundProbeReportCache,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
    ProbeExpectation,
    ProbeReportError,
)
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    RunnerConfig,
    RunnerError,
)


RUN_ID = UUID("11111111-1111-4111-8111-111111111111")
NOVEL_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
AUTO_REQUEST = UUID("44444444-4444-4444-8444-444444444444")
AUTO_EDITION = UUID("55555555-5555-4555-8555-555555555555")
MANUAL_REQUEST = UUID("66666666-6666-4666-8666-666666666666")
MANUAL_EDITION = UUID("77777777-7777-4777-8777-777777777777")
AUTO_EDITION_FINGERPRINT = "c" * 64
MANUAL_EDITION_FINGERPRINT = "d" * 64
OUTPUT_HASHES = ("a" * 64, "b" * 64)


def _config(tmp_path: Path, *, mode: int = 0o700) -> RunnerConfig:
    private = tmp_path / "private"
    private.mkdir(mode=mode)
    private.chmod(mode)
    return RunnerConfig(
        run_id=RUN_ID,
        mode="real",
        fixture_manifest=tmp_path / "fixture.json",
        api_base="http://127.0.0.1:18088/api/ai-novel-world-2026",
        novel_id=NOVEL_ID,
        document_id=DOCUMENT_ID,
        automatic_case_id="automatic",
        manual_case_id="manual",
        private_work_dir=private,
        output_dir=tmp_path / "output",
        duration_minutes=30.0,
        listening_record=None,
        resume=False,
    )


def _expectation(config: RunnerConfig) -> ProbeExpectation:
    return ProbeExpectation.from_runner(
        config,
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        listening_output_hashes=OUTPUT_HASHES,
    )


def _context() -> TechnicalProbeContext:
    return TechnicalProbeContext(
        automatic_request_id=AUTO_REQUEST,
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        automatic_manifest_revision=2,
        manual_request_id=MANUAL_REQUEST,
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        manual_manifest_revision=2,
        request_to_ready_seconds=(10.0, 20.0),
        observed_http_first_audio_ms=(500, 700),
        chapter_audio_duration_seconds=90.0,
        range_status_codes=EXPECTED_RANGE_STATUS_CODES,
        listening_output_hashes=OUTPUT_HASHES,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_publisher_writes_one_redacted_private_handshake(tmp_path: Path) -> None:
    config = _config(tmp_path)
    expectation = _expectation(config)
    publisher = PrivateProbeRequestPublisher(
        preflight_payload_sha256="a" * 64,
        now=lambda: datetime(2026, 8, 27, 1, 2, 3, tzinfo=timezone.utc)
    )

    publisher.publish(config, expectation, _context())

    path = config.private_work_dir / PROBE_REQUEST_FILENAME
    metadata = path.lstat()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(metadata.st_mode) == 0o600
    assert metadata.st_nlink == 1
    assert set(payload) == {
        "schema_version",
        "report_schema_version",
        "created_at",
        "controller_preflight_payload_sha256",
        "binding_seed",
        "performance_seed",
        "required_captures",
        "runtime_contract",
        "request_fingerprint_sha256",
    }
    assert payload["schema_version"] == PROBE_REQUEST_SCHEMA_VERSION
    assert payload["report_schema_version"] == PROBE_SCHEMA_VERSION
    assert payload["created_at"] == "2026-08-27T01:02:03Z"
    assert payload["controller_preflight_payload_sha256"] == "a" * 64
    assert payload["binding_seed"] == {
        "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
        "target_scope_sha256": expectation.target_scope_sha256,
        "automatic_edition_id_sha256": expectation.automatic_edition_id_sha256,
        "manual_edition_id_sha256": expectation.manual_edition_id_sha256,
        "automatic_edition_fingerprint_sha256": (
            expectation.automatic_edition_fingerprint_sha256
        ),
        "manual_edition_fingerprint_sha256": (
            expectation.manual_edition_fingerprint_sha256
        ),
        "listening_output_hashes": list(OUTPUT_HASHES),
        "required_stability_seconds": 1800.0,
    }
    assert payload["performance_seed"] == {
        "request_to_ready_seconds": [10.0, 20.0],
        "observed_http_first_audio_ms": [500, 700],
        "chapter_audio_duration_seconds": 90.0,
    }
    assert payload["required_captures"] == [
        {
            "width": width,
            "height": height,
            "assistant_mode": assistant_mode,
        }
        for width, height in ALLOWED_VIEWPORTS
        for assistant_mode in ALLOWED_ASSISTANT_MODES
    ]
    assert payload["runtime_contract"] == {
        "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
        "range_status_codes": list(EXPECTED_RANGE_STATUS_CODES),
    }
    unsigned = dict(payload)
    fingerprint = unsigned.pop("request_fingerprint_sha256")
    assert fingerprint == hashlib.sha256(_canonical(unsigned)).hexdigest()
    serialized = path.read_text(encoding="utf-8")
    assert all(
        raw not in serialized
        for raw in map(
            str,
            (
                RUN_ID,
                NOVEL_ID,
                DOCUMENT_ID,
                AUTO_REQUEST,
                AUTO_EDITION,
                MANUAL_REQUEST,
                MANUAL_EDITION,
            ),
        )
    )


def test_probe_request_schema_is_forward_only_one_three() -> None:
    assert PROBE_REQUEST_SCHEMA_VERSION == (
        "moss-tts-chapter-e2e-probe-request/1.3"
    )


def test_publisher_rejects_invalid_performance_seed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    invalid = TechnicalProbeContext(
        automatic_request_id=AUTO_REQUEST,
        automatic_edition_id=AUTO_EDITION,
        automatic_edition_fingerprint=AUTO_EDITION_FINGERPRINT,
        automatic_manifest_revision=2,
        manual_request_id=MANUAL_REQUEST,
        manual_edition_id=MANUAL_EDITION,
        manual_edition_fingerprint=MANUAL_EDITION_FINGERPRINT,
        manual_manifest_revision=2,
        request_to_ready_seconds=(10.0, float("nan")),
        observed_http_first_audio_ms=(500, 700),
        chapter_audio_duration_seconds=90.0,
        range_status_codes=EXPECTED_RANGE_STATUS_CODES,
        listening_output_hashes=OUTPUT_HASHES,
    )

    with pytest.raises(RunnerError, match="PROBE_REQUEST_PERFORMANCE_INVALID"):
        PrivateProbeRequestPublisher(
            preflight_payload_sha256="a" * 64
        ).publish(config, _expectation(config), invalid)


def test_publisher_never_overwrites_an_existing_request(tmp_path: Path) -> None:
    config = _config(tmp_path)
    publisher = PrivateProbeRequestPublisher(
        preflight_payload_sha256="a" * 64
    )
    publisher.publish(config, _expectation(config), _context())

    with pytest.raises(RunnerError, match="PROBE_REQUEST_EXISTS"):
        publisher.publish(config, _expectation(config), _context())


def test_publisher_rejects_non_private_work_directory(tmp_path: Path) -> None:
    config = _config(tmp_path, mode=0o755)

    with pytest.raises(RunnerError, match="PROBE_REQUEST_DIRECTORY_UNSAFE"):
        PrivateProbeRequestPublisher(
            preflight_payload_sha256="a" * 64
        ).publish(config, _expectation(config), _context())


def test_cache_publishes_handshake_before_waiting_for_report(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    class Publisher:
        calls: list[
            tuple[RunnerConfig, ProbeExpectation, TechnicalProbeContext]
        ] = []

        def publish(
            self,
            actual_config: RunnerConfig,
            expectation: ProbeExpectation,
            context: TechnicalProbeContext,
        ) -> None:
            self.calls.append((actual_config, expectation, context))

    clock = Clock()
    publisher = Publisher()
    cache = BoundProbeReportCache(
        tmp_path / "missing.json",
        wait_timeout_seconds=1.0,
        poll_interval_seconds=0.5,
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
        request_publisher=publisher,
    )

    with pytest.raises(ProbeReportError, match="PROBE_REPORT_TIMEOUT"):
        cache.load(config, _context())

    assert len(publisher.calls) == 1
    assert publisher.calls[0] == (config, _expectation(config), _context())
