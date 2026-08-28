#!/usr/bin/env python3
"""Publish the minimal private handshake needed by the T4-K probe harness.

The real executor learns random run, Edition, and output identities only after
both chapter chains complete.  This publisher writes their hashes—not raw IDs,
chapter text, audio, paths, or credentials—to one ``0600`` file in the already
validated repository-external private work directory.  The external collector
uses ``binding_seed`` to build the final, timestamp-bound probe report.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Callable, Final

from scripts.tts.chapter_e2e_probes import (
    ALLOWED_ASSISTANT_MODES,
    EXPECTED_RANGE_STATUS_CODES,
    EXPECTED_SIDECAR_CONTAINER_NAME,
    PROBE_SCHEMA_VERSION,
    ProbeExpectation,
)
from scripts.tts.chapter_e2e_executor import TechnicalProbeContext
from scripts.tts.validate_chapter_e2e import (
    ALLOWED_VIEWPORTS,
    REPOSITORY_ROOT,
    RunnerConfig,
    RunnerError,
)


PROBE_REQUEST_SCHEMA_VERSION: Final = (
    "moss-tts-chapter-e2e-probe-request/1.3"
)
PROBE_REQUEST_FILENAME: Final = "probe-request.json"
PROBE_REPORT_FILENAME: Final = "probe-report.json"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class PrivateProbeRequestPublisher:
    """Create one non-overwriting, redacted probe request for a real run."""

    def __init__(
        self,
        *,
        preflight_payload_sha256: str,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        # The wire key retains its historical name for compatibility with the
        # experimental signed-controller candidate.  In the active personal
        # local path this digest is an unsigned fixed-executor binding; it is
        # not a preflight signature or cryptographic authority assertion.
        self._preflight_payload_sha256 = preflight_payload_sha256
        if (
            not callable(self._now)
            or type(preflight_payload_sha256) is not str
            or len(preflight_payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in preflight_payload_sha256
            )
        ):
            raise RunnerError("PROBE_REQUEST_POLICY_INVALID")

    def publish(
        self,
        config: RunnerConfig,
        expectation: ProbeExpectation,
        context: TechnicalProbeContext,
    ) -> None:
        if (
            type(config) is not RunnerConfig
            or type(expectation) is not ProbeExpectation
            or type(context) is not TechnicalProbeContext
        ):
            raise RunnerError("PROBE_REQUEST_SCOPE_INVALID")
        request_to_ready_seconds = context.request_to_ready_seconds
        observed_http_first_audio_ms = context.observed_http_first_audio_ms
        chapter_audio_duration_seconds = context.chapter_audio_duration_seconds
        if (
            type(request_to_ready_seconds) is not tuple
            or len(request_to_ready_seconds) != 2
            or any(
                type(value) not in {int, float}
                or not math.isfinite(float(value))
                or float(value) < 0
                for value in request_to_ready_seconds
            )
            or type(observed_http_first_audio_ms) is not tuple
            or len(observed_http_first_audio_ms) != 2
            or any(
                type(value) is not int or value < 0
                for value in observed_http_first_audio_ms
            )
            or type(chapter_audio_duration_seconds) not in {int, float}
            or not math.isfinite(float(chapter_audio_duration_seconds))
            or float(chapter_audio_duration_seconds) <= 0
        ):
            raise RunnerError("PROBE_REQUEST_PERFORMANCE_INVALID")
        directory = config.private_work_dir
        if not directory.is_absolute() or ".." in directory.parts:
            raise RunnerError("PROBE_REQUEST_DIRECTORY_UNSAFE")
        try:
            resolved = directory.resolve(strict=True)
            repository = REPOSITORY_ROOT.resolve(strict=True)
        except OSError as error:
            raise RunnerError("PROBE_REQUEST_DIRECTORY_UNSAFE") from error
        if resolved == repository or resolved.is_relative_to(repository):
            raise RunnerError("PROBE_REQUEST_DIRECTORY_UNSAFE")

        current = self._now()
        if type(current) is not datetime or current.tzinfo is None:
            raise RunnerError("PROBE_REQUEST_TIME_INVALID")
        created_at = current.astimezone(timezone.utc).replace(microsecond=0)
        created_at_text = created_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        binding_seed: dict[str, object] = {
            "run_fingerprint_sha256": expectation.run_fingerprint_sha256,
            "target_scope_sha256": expectation.target_scope_sha256,
            "automatic_edition_id_sha256": (
                expectation.automatic_edition_id_sha256
            ),
            "manual_edition_id_sha256": expectation.manual_edition_id_sha256,
            "automatic_edition_fingerprint_sha256": (
                expectation.automatic_edition_fingerprint_sha256
            ),
            "manual_edition_fingerprint_sha256": (
                expectation.manual_edition_fingerprint_sha256
            ),
            "listening_output_hashes": list(
                expectation.listening_output_hashes
            ),
            "required_stability_seconds": (
                expectation.required_stability_seconds
            ),
        }
        unsigned: dict[str, object] = {
            "schema_version": PROBE_REQUEST_SCHEMA_VERSION,
            "report_schema_version": PROBE_SCHEMA_VERSION,
            "created_at": created_at_text,
            "controller_preflight_payload_sha256": (
                self._preflight_payload_sha256
            ),
            "binding_seed": binding_seed,
            "performance_seed": {
                "request_to_ready_seconds": [
                    float(value) for value in request_to_ready_seconds
                ],
                "observed_http_first_audio_ms": list(
                    observed_http_first_audio_ms
                ),
                "chapter_audio_duration_seconds": float(
                    chapter_audio_duration_seconds
                ),
            },
            "required_captures": [
                {
                    "width": width,
                    "height": height,
                    "assistant_mode": assistant_mode,
                }
                for width, height in ALLOWED_VIEWPORTS
                for assistant_mode in ALLOWED_ASSISTANT_MODES
            ],
            "runtime_contract": {
                "sidecar_container_name": EXPECTED_SIDECAR_CONTAINER_NAME,
                "range_status_codes": list(EXPECTED_RANGE_STATUS_CODES),
            },
        }
        payload = {
            **unsigned,
            "request_fingerprint_sha256": hashlib.sha256(
                _canonical_json(unsigned)
            ).hexdigest(),
        }
        data = _canonical_json(payload) + b"\n"
        self._write_exclusive(resolved, data)

    @staticmethod
    def _write_exclusive(directory: Path, data: bytes) -> None:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise RunnerError("PROBE_REQUEST_POLICY_UNAVAILABLE")
        directory_descriptor: int | None = None
        file_descriptor: int | None = None
        try:
            directory_descriptor = os.open(
                directory,
                os.O_RDONLY
                | os.O_DIRECTORY
                | getattr(os, "O_CLOEXEC", 0)
                | nofollow,
            )
            details = os.fstat(directory_descriptor)
            if (
                not stat.S_ISDIR(details.st_mode)
                or stat.S_IMODE(details.st_mode) != 0o700
                or details.st_uid != os.getuid()
            ):
                raise RunnerError("PROBE_REQUEST_DIRECTORY_UNSAFE")
            try:
                file_descriptor = os.open(
                    PROBE_REQUEST_FILENAME,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | nofollow,
                    0o600,
                    dir_fd=directory_descriptor,
                )
            except FileExistsError as error:
                raise RunnerError("PROBE_REQUEST_EXISTS") from error
            opened = os.fstat(file_descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or stat.S_IMODE(opened.st_mode) != 0o600
                or opened.st_uid != os.getuid()
            ):
                raise RunnerError("PROBE_REQUEST_FILE_UNSAFE")
            offset = 0
            while offset < len(data):
                written = os.write(file_descriptor, data[offset:])
                if written <= 0:
                    raise RunnerError("PROBE_REQUEST_WRITE_FAILED")
                offset += written
            os.fsync(file_descriptor)
            os.fsync(directory_descriptor)
        except RunnerError:
            raise
        except OSError as error:
            raise RunnerError("PROBE_REQUEST_WRITE_FAILED") from error
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if directory_descriptor is not None:
                os.close(directory_descriptor)


__all__ = [
    "PROBE_REQUEST_FILENAME",
    "PROBE_REQUEST_SCHEMA_VERSION",
    "PrivateProbeRequestPublisher",
]
