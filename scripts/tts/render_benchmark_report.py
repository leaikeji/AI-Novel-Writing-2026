#!/usr/bin/env python3
"""Validate MOSS-TTS benchmark metrics and render Markdown/JSON summaries."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


RESULT_SCHEMA_VERSION = "moss-tts-benchmark-result/1.0"
SUMMARY_SCHEMA_VERSION = "moss-tts-benchmark-summary/1.0"
AUDIO_SCHEMA_VERSION = "moss-tts-audio-inspection/1.0"
RUN_STATUSES = (
    "pending",
    "running",
    "passed",
    "partial",
    "failed",
    "cancelled",
    "crashed",
    "skipped",
    "blocked",
)
CASE_STATUSES = (
    "passed",
    "failed",
    "cancelled",
    "crashed",
    "skipped",
    "blocked",
)
HASH_STATUSES = ("verified", "unavailable", "not_applicable")
LISTENING_STATUSES = ("pending", "completed", "not_required", "skipped_with_reason")
LISTENING_VERDICTS = ("pass", "fail", "inconclusive", "not_reviewed")
DEFECT_KEYS = (
    "missing_text",
    "repeated_text",
    "voice_drift",
    "abnormal_pauses",
    "seam_artifacts",
    "clipping_or_noise",
    "loudness_inconsistent",
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
WORK_PACKAGE_IDS = ("T0-B", "T0-C", "T0-D", "T4-K")


class ContractValidationError(ValueError):
    """Raised when a benchmark result does not match the frozen contract."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def sha256_file(input_path: Path) -> str:
    digest = hashlib.sha256()
    with input_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_mapping(
    value: object,
    path: str,
    errors: list[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{path}: expected object")
        return {}
    return value


def require_list(value: object, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: expected array")
        return []
    return value


def require_keys(
    value: dict[str, Any],
    keys: tuple[str, ...],
    path: str,
    errors: list[str],
) -> None:
    for key in keys:
        if key not in value:
            errors.append(f"{path}.{key}: required field is missing")


def require_non_empty_string(value: object, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: expected non-empty string")


def require_hash_or_null(
    value: object,
    hash_status: object,
    path: str,
    status_path: str,
    errors: list[str],
) -> None:
    if hash_status not in HASH_STATUSES:
        errors.append(f"{status_path}: expected one of {', '.join(HASH_STATUSES)}")
        return
    if hash_status == "verified":
        if not isinstance(value, str) or not HEX_64.fullmatch(value):
            errors.append(f"{path}: verified hash must be lowercase SHA-256")
    elif value is not None:
        errors.append(f"{path}: must be null when hash status is {hash_status}")


def require_number_or_null(
    value: object,
    path: str,
    errors: list[str],
    *,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.append(f"{path}: expected number or null")
        return
    if not math.isfinite(float(value)) or float(value) < minimum:
        errors.append(f"{path}: expected finite number >= {minimum}")
    elif maximum is not None and float(value) > maximum:
        errors.append(f"{path}: expected number <= {maximum}")


def require_timestamp_or_null(
    value: object,
    path: str,
    errors: list[str],
) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{path}: expected ISO 8601 string or null")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{path}: invalid ISO 8601 timestamp")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{path}: timezone offset is required")
        return None
    return parsed


def validate_environment(environment: dict[str, Any], path: str, errors: list[str]) -> None:
    required = (
        "hardware",
        "os_name",
        "os_version",
        "architecture",
        "python_version",
        "physical_memory_bytes",
    )
    require_keys(environment, required, path, errors)
    for key in required[:-1]:
        require_non_empty_string(environment.get(key), f"{path}.{key}", errors)
    memory = environment.get("physical_memory_bytes")
    if isinstance(memory, bool) or not isinstance(memory, int) or memory <= 0:
        errors.append(f"{path}.physical_memory_bytes: expected positive integer")


def validate_model(model: dict[str, Any], path: str, errors: list[str]) -> None:
    require_keys(
        model,
        (
            "name",
            "revision",
            "revision_sha256",
            "revision_hash_status",
            "execution_backend",
            "artifacts",
        ),
        path,
        errors,
    )
    for key in ("name", "revision", "execution_backend"):
        require_non_empty_string(model.get(key), f"{path}.{key}", errors)
    require_hash_or_null(
        model.get("revision_sha256"),
        model.get("revision_hash_status"),
        f"{path}.revision_sha256",
        f"{path}.revision_hash_status",
        errors,
    )
    artifacts = require_list(model.get("artifacts"), f"{path}.artifacts", errors)
    if not artifacts:
        errors.append(f"{path}.artifacts: at least one artifact record is required")
    for index, raw_artifact in enumerate(artifacts):
        artifact_path = f"{path}.artifacts[{index}]"
        artifact = require_mapping(raw_artifact, artifact_path, errors)
        require_keys(
            artifact,
            ("name", "revision", "sha256", "hash_status", "source"),
            artifact_path,
            errors,
        )
        for key in ("name", "revision", "source"):
            require_non_empty_string(artifact.get(key), f"{artifact_path}.{key}", errors)
        require_hash_or_null(
            artifact.get("sha256"),
            artifact.get("hash_status"),
            f"{artifact_path}.sha256",
            f"{artifact_path}.hash_status",
            errors,
        )


def validate_audio_inspection(
    inspection: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    required = (
        "schema_version",
        "status",
        "source",
        "sample_rate_hz",
        "channels",
        "sample_width_bytes",
        "frame_count",
        "duration_seconds",
        "peak_abs_normalized",
        "rms_normalized",
        "silent_frame_ratio",
        "clipped_sample_ratio",
    )
    require_keys(inspection, required, path, errors)
    if inspection.get("schema_version") != AUDIO_SCHEMA_VERSION:
        errors.append(f"{path}.schema_version: expected {AUDIO_SCHEMA_VERSION}")
    if inspection.get("status") != "ok":
        errors.append(f"{path}.status: successful case requires 'ok'")
    source = require_mapping(inspection.get("source"), f"{path}.source", errors)
    require_keys(
        source,
        ("file_name", "file_size_bytes", "sha256", "read_only_inspection"),
        f"{path}.source",
        errors,
    )
    require_non_empty_string(source.get("file_name"), f"{path}.source.file_name", errors)
    if not isinstance(source.get("sha256"), str) or not HEX_64.fullmatch(source["sha256"]):
        errors.append(f"{path}.source.sha256: expected lowercase SHA-256")
    if source.get("read_only_inspection") is not True:
        errors.append(f"{path}.source.read_only_inspection: expected true")
    file_size = source.get("file_size_bytes")
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0:
        errors.append(f"{path}.source.file_size_bytes: expected non-negative integer")
    for key in ("sample_rate_hz", "channels", "sample_width_bytes"):
        value = inspection.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            errors.append(f"{path}.{key}: expected positive integer")
    frame_count = inspection.get("frame_count")
    if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 0:
        errors.append(f"{path}.frame_count: expected non-negative integer")
    require_number_or_null(
        inspection.get("duration_seconds"), f"{path}.duration_seconds", errors
    )
    if inspection.get("duration_seconds") is None:
        errors.append(f"{path}.duration_seconds: expected a measurement")
    for key in ("peak_abs_normalized", "rms_normalized", "silent_frame_ratio", "clipped_sample_ratio"):
        require_number_or_null(
            inspection.get(key),
            f"{path}.{key}",
            errors,
            maximum=1.0,
        )
        if inspection.get(key) is None:
            errors.append(f"{path}.{key}: expected a measurement")


def validate_case(raw_case: object, index: int, errors: list[str]) -> None:
    path = f"$.cases[{index}]"
    case = require_mapping(raw_case, path, errors)
    require_keys(
        case,
        (
            "case_id",
            "status",
            "input",
            "timing",
            "resources",
            "output",
            "control",
            "error",
            "listening",
        ),
        path,
        errors,
    )
    require_non_empty_string(case.get("case_id"), f"{path}.case_id", errors)
    status = case.get("status")
    if status not in CASE_STATUSES:
        errors.append(f"{path}.status: expected one of {', '.join(CASE_STATUSES)}")

    input_data = require_mapping(case.get("input"), f"{path}.input", errors)
    require_keys(
        input_data,
        (
            "text_ids",
            "text_sha256",
            "combined_sha256",
            "reference_profile_id",
            "reference_sha256",
        ),
        f"{path}.input",
        errors,
    )
    text_ids = require_list(input_data.get("text_ids"), f"{path}.input.text_ids", errors)
    text_hashes = require_list(
        input_data.get("text_sha256"), f"{path}.input.text_sha256", errors
    )
    if not text_ids:
        errors.append(f"{path}.input.text_ids: at least one fixture text is required")
    if len(text_ids) != len(text_hashes):
        errors.append(f"{path}.input: text_ids and text_sha256 lengths differ")
    for text_index, text_id in enumerate(text_ids):
        require_non_empty_string(text_id, f"{path}.input.text_ids[{text_index}]", errors)
    for hash_index, text_hash in enumerate(text_hashes):
        if not isinstance(text_hash, str) or not HEX_64.fullmatch(text_hash):
            errors.append(
                f"{path}.input.text_sha256[{hash_index}]: expected lowercase SHA-256"
            )
    combined_hash = input_data.get("combined_sha256")
    if not isinstance(combined_hash, str) or not HEX_64.fullmatch(combined_hash):
        errors.append(f"{path}.input.combined_sha256: expected lowercase SHA-256")
    reference_hash = input_data.get("reference_sha256")
    reference_profile_id = input_data.get("reference_profile_id")
    if reference_profile_id is not None and (
        not isinstance(reference_profile_id, str) or not reference_profile_id.strip()
    ):
        errors.append(f"{path}.input.reference_profile_id: expected non-empty string or null")
    if reference_hash is not None and (
        not isinstance(reference_hash, str) or not HEX_64.fullmatch(reference_hash)
    ):
        errors.append(f"{path}.input.reference_sha256: expected SHA-256 or null")

    timing = require_mapping(case.get("timing"), f"{path}.timing", errors)
    require_keys(
        timing,
        ("first_packet_ms", "synthesis_wall_ms", "audio_duration_seconds", "rtf"),
        f"{path}.timing",
        errors,
    )
    for key in ("first_packet_ms", "synthesis_wall_ms", "audio_duration_seconds", "rtf"):
        require_number_or_null(timing.get(key), f"{path}.timing.{key}", errors)
    synthesis_wall_ms = timing.get("synthesis_wall_ms")
    audio_duration_seconds = timing.get("audio_duration_seconds")
    reported_rtf = timing.get("rtf")
    if (
        isinstance(synthesis_wall_ms, (int, float))
        and not isinstance(synthesis_wall_ms, bool)
        and isinstance(audio_duration_seconds, (int, float))
        and not isinstance(audio_duration_seconds, bool)
        and audio_duration_seconds > 0
        and isinstance(reported_rtf, (int, float))
        and not isinstance(reported_rtf, bool)
    ):
        calculated_rtf = float(synthesis_wall_ms) / 1000.0 / float(audio_duration_seconds)
        if not math.isclose(float(reported_rtf), calculated_rtf, rel_tol=1e-6, abs_tol=1e-9):
            errors.append(
                f"{path}.timing.rtf: expected {calculated_rtf:.9f} from wall time/audio duration"
            )
    if status == "passed":
        for key in ("first_packet_ms", "synthesis_wall_ms", "audio_duration_seconds", "rtf"):
            if timing.get(key) is None:
                errors.append(f"{path}.timing.{key}: passed case requires a measurement")

    resources = require_mapping(case.get("resources"), f"{path}.resources", errors)
    require_keys(
        resources,
        ("peak_rss_bytes", "peak_accelerator_bytes"),
        f"{path}.resources",
        errors,
    )
    for key in ("peak_rss_bytes", "peak_accelerator_bytes"):
        value = resources.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            errors.append(f"{path}.resources.{key}: expected non-negative integer or null")
    if status == "passed" and resources.get("peak_rss_bytes") is None:
        errors.append(f"{path}.resources.peak_rss_bytes: passed case requires a measurement")

    output = require_mapping(case.get("output"), f"{path}.output", errors)
    require_keys(
        output,
        ("audio_sha256", "audio_inspection", "ready_segment_sha256"),
        f"{path}.output",
        errors,
    )
    audio_hash = output.get("audio_sha256")
    inspection = output.get("audio_inspection")
    ready_hashes = require_list(
        output.get("ready_segment_sha256"),
        f"{path}.output.ready_segment_sha256",
        errors,
    )
    for ready_index, ready_hash in enumerate(ready_hashes):
        if not isinstance(ready_hash, str) or not HEX_64.fullmatch(ready_hash):
            errors.append(
                f"{path}.output.ready_segment_sha256[{ready_index}]: expected lowercase SHA-256"
            )
    if status == "passed":
        if not isinstance(audio_hash, str) or not HEX_64.fullmatch(audio_hash):
            errors.append(f"{path}.output.audio_sha256: passed case requires SHA-256")
        validate_audio_inspection(
            require_mapping(inspection, f"{path}.output.audio_inspection", errors),
            f"{path}.output.audio_inspection",
            errors,
        )
        if isinstance(inspection, dict):
            source = inspection.get("source")
            if isinstance(source, dict) and audio_hash != source.get("sha256"):
                errors.append(
                    f"{path}.output: audio_sha256 must match audio_inspection.source.sha256"
                )
            inspected_duration = inspection.get("duration_seconds")
            timed_duration = timing.get("audio_duration_seconds")
            if (
                isinstance(inspected_duration, (int, float))
                and not isinstance(inspected_duration, bool)
                and isinstance(timed_duration, (int, float))
                and not isinstance(timed_duration, bool)
                and not math.isclose(
                    float(inspected_duration),
                    float(timed_duration),
                    rel_tol=1e-6,
                    abs_tol=1e-9,
                )
            ):
                errors.append(
                    f"{path}.timing.audio_duration_seconds: must match audio inspection"
                )
    elif audio_hash is not None or inspection is not None:
        errors.append(f"{path}.output: non-passed case must not claim an audio artifact")

    control = require_mapping(case.get("control"), f"{path}.control", errors)
    require_keys(
        control,
        (
            "cancel_requested",
            "cancel_acknowledged",
            "failure_injected",
            "crash_recovered",
            "ready_segments_reused",
        ),
        f"{path}.control",
        errors,
    )
    for key in ("cancel_requested", "cancel_acknowledged", "failure_injected", "crash_recovered"):
        if not isinstance(control.get(key), bool):
            errors.append(f"{path}.control.{key}: expected boolean")
    reused = control.get("ready_segments_reused")
    if isinstance(reused, bool) or not isinstance(reused, int) or reused < 0:
        errors.append(f"{path}.control.ready_segments_reused: expected non-negative integer")
    if control.get("cancel_acknowledged") and not control.get("cancel_requested"):
        errors.append(f"{path}.control: cancellation cannot be acknowledged before request")
    if status == "cancelled" and not (
        control.get("cancel_requested") and control.get("cancel_acknowledged")
    ):
        errors.append(f"{path}.control: cancelled case requires requested and acknowledged")
    if isinstance(reused, int) and reused > len(ready_hashes):
        errors.append(
            f"{path}.control.ready_segments_reused: cannot exceed recorded ready segment hashes"
        )

    error = case.get("error")
    if error is not None:
        error_data = require_mapping(error, f"{path}.error", errors)
        require_keys(error_data, ("category", "code", "message_redacted"), f"{path}.error", errors)
        for key in ("category", "code", "message_redacted"):
            require_non_empty_string(error_data.get(key), f"{path}.error.{key}", errors)
    if status in {"failed", "cancelled", "crashed", "blocked"} and error is None:
        errors.append(f"{path}.error: {status} case requires a redacted error record")
    if status == "passed" and error is not None:
        errors.append(f"{path}.error: passed case must not contain an error")

    listening = require_mapping(case.get("listening"), f"{path}.listening", errors)
    require_keys(
        listening,
        ("status", "reviewer", "verdict", "defects", "notes_redacted", "skipped_reason"),
        f"{path}.listening",
        errors,
    )
    if listening.get("status") not in LISTENING_STATUSES:
        errors.append(
            f"{path}.listening.status: expected one of {', '.join(LISTENING_STATUSES)}"
        )
    if listening.get("verdict") not in LISTENING_VERDICTS:
        errors.append(
            f"{path}.listening.verdict: expected one of {', '.join(LISTENING_VERDICTS)}"
        )
    for key in ("reviewer", "notes_redacted", "skipped_reason"):
        if listening.get(key) is not None and not isinstance(listening.get(key), str):
            errors.append(f"{path}.listening.{key}: expected string or null")
    defects = require_mapping(listening.get("defects"), f"{path}.listening.defects", errors)
    require_keys(defects, DEFECT_KEYS, f"{path}.listening.defects", errors)
    for key in DEFECT_KEYS:
        if defects.get(key) is not None and not isinstance(defects.get(key), bool):
            errors.append(f"{path}.listening.defects.{key}: expected boolean or null")
    if listening.get("status") == "completed":
        if not listening.get("reviewer"):
            errors.append(f"{path}.listening.reviewer: completed review requires reviewer")
        if listening.get("verdict") == "not_reviewed":
            errors.append(f"{path}.listening.verdict: completed review needs a verdict")
    if listening.get("status") == "skipped_with_reason" and not listening.get("skipped_reason"):
        errors.append(f"{path}.listening.skipped_reason: skip requires a reason")


def validate_result(payload: object, source_name: str) -> dict[str, Any]:
    errors: list[str] = []
    root = require_mapping(payload, "$", errors)
    require_keys(root, ("schema_version", "run", "cases"), "$", errors)
    if root.get("schema_version") != RESULT_SCHEMA_VERSION:
        errors.append(f"$.schema_version: expected {RESULT_SCHEMA_VERSION}")

    run = require_mapping(root.get("run"), "$.run", errors)
    require_keys(
        run,
        (
            "run_id",
            "benchmark_id",
            "work_package_id",
            "status",
            "started_at",
            "finished_at",
            "environment",
            "model",
            "parameters",
            "command",
            "privacy",
        ),
        "$.run",
        errors,
    )
    for key in ("run_id", "benchmark_id", "work_package_id"):
        require_non_empty_string(run.get(key), f"$.run.{key}", errors)
    if run.get("work_package_id") not in WORK_PACKAGE_IDS:
        errors.append(
            f"$.run.work_package_id: expected one of {', '.join(WORK_PACKAGE_IDS)}"
        )
    started_at = require_timestamp_or_null(run.get("started_at"), "$.run.started_at", errors)
    finished_at = require_timestamp_or_null(run.get("finished_at"), "$.run.finished_at", errors)
    if started_at is None:
        errors.append("$.run.started_at: required field cannot be null")
    if run.get("status") not in {"pending", "running"} and finished_at is None:
        errors.append("$.run.finished_at: terminal run requires a timestamp")
    if started_at is not None and finished_at is not None and finished_at < started_at:
        errors.append("$.run.finished_at: cannot be earlier than started_at")
    if run.get("status") not in RUN_STATUSES:
        errors.append(f"$.run.status: expected one of {', '.join(RUN_STATUSES)}")
    validate_environment(
        require_mapping(run.get("environment"), "$.run.environment", errors),
        "$.run.environment",
        errors,
    )
    validate_model(
        require_mapping(run.get("model"), "$.run.model", errors),
        "$.run.model",
        errors,
    )
    require_mapping(run.get("parameters"), "$.run.parameters", errors)

    command = require_mapping(run.get("command"), "$.run.command", errors)
    require_keys(command, ("argv", "exit_code"), "$.run.command", errors)
    argv = require_list(command.get("argv"), "$.run.command.argv", errors)
    if not argv or not all(isinstance(item, str) and item for item in argv):
        errors.append("$.run.command.argv: expected at least one non-empty argument")
    exit_code = command.get("exit_code")
    if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
        errors.append("$.run.command.exit_code: expected integer or null")
    if run.get("status") not in {"pending", "running"} and exit_code is None:
        errors.append("$.run.command.exit_code: terminal run requires an exit code")

    privacy = require_mapping(run.get("privacy"), "$.run.privacy", errors)
    privacy_keys = (
        "fixture_only",
        "contains_user_text",
        "contains_private_reference_audio",
        "evidence_contains_audio",
    )
    require_keys(privacy, privacy_keys, "$.run.privacy", errors)
    for key in privacy_keys:
        if not isinstance(privacy.get(key), bool):
            errors.append(f"$.run.privacy.{key}: expected boolean")
    if privacy.get("fixture_only") is not True:
        errors.append("$.run.privacy.fixture_only: T0/T4 benchmark evidence must use frozen fixtures")
    for key in (
        "contains_user_text",
        "contains_private_reference_audio",
        "evidence_contains_audio",
    ):
        if privacy.get(key) is not False:
            errors.append(f"$.run.privacy.{key}: evidence boundary requires false")

    cases = require_list(root.get("cases"), "$.cases", errors)
    if not cases:
        errors.append("$.cases: at least one case is required")
    observed_case_ids: set[str] = set()
    for index, raw_case in enumerate(cases):
        validate_case(raw_case, index, errors)
        if isinstance(raw_case, dict) and isinstance(raw_case.get("case_id"), str):
            case_id = raw_case["case_id"]
            if case_id in observed_case_ids:
                errors.append(f"$.cases[{index}].case_id: duplicate {case_id!r}")
            observed_case_ids.add(case_id)

    observed_statuses = [
        raw_case.get("status")
        for raw_case in cases
        if isinstance(raw_case, dict)
    ]
    if run.get("status") == "passed" and any(status != "passed" for status in observed_statuses):
        errors.append("$.run.status: passed requires every case to be passed")
    if run.get("status") == "partial" and not (
        "passed" in observed_statuses and any(status != "passed" for status in observed_statuses)
    ):
        errors.append("$.run.status: partial requires both passed and non-passed cases")
    if run.get("status") in {"cancelled", "crashed"} and run.get("status") not in observed_statuses:
        errors.append(f"$.run.status: {run.get('status')} requires a matching case status")

    if errors:
        raise ContractValidationError([f"{source_name}: {error}" for error in errors])
    return root


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile_value * len(ordered)))
    return ordered[rank - 1]


def rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def metric_summary(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "median": rounded(percentile(values, 0.5)),
        "p95": rounded(percentile(values, 0.95)),
        "max": rounded(max(values) if values else None),
    }


def ordered_counts(counter: Counter[str], order: tuple[str, ...]) -> dict[str, int]:
    return {key: counter[key] for key in order if counter[key]}


def build_summary(
    validated: list[tuple[Path, str, dict[str, Any]]],
) -> dict[str, Any]:
    run_statuses: Counter[str] = Counter()
    case_statuses: Counter[str] = Counter()
    listening_statuses: Counter[str] = Counter()
    listening_verdicts: Counter[str] = Counter()
    defects: Counter[str] = Counter()
    first_packet: list[float] = []
    rtf: list[float] = []
    peak_rss: list[int] = []
    peak_accelerator: list[int] = []
    cancel_requested = 0
    cancel_acknowledged = 0
    failure_injected = 0
    crash_recovered = 0
    ready_segments_reused = 0
    ready_segment_outputs = 0
    case_count = 0
    runs: list[dict[str, Any]] = []
    sources: list[dict[str, str]] = []

    for source_path, source_hash, result in validated:
        run = result["run"]
        run_statuses[run["status"]] += 1
        sources.append({"file_name": source_path.name, "sha256": source_hash})
        local_case_statuses: Counter[str] = Counter()
        for case in result["cases"]:
            case_count += 1
            case_statuses[case["status"]] += 1
            local_case_statuses[case["status"]] += 1
            timing = case["timing"]
            if timing["first_packet_ms"] is not None:
                first_packet.append(float(timing["first_packet_ms"]))
            if timing["rtf"] is not None:
                rtf.append(float(timing["rtf"]))
            resources = case["resources"]
            if resources["peak_rss_bytes"] is not None:
                peak_rss.append(resources["peak_rss_bytes"])
            if resources["peak_accelerator_bytes"] is not None:
                peak_accelerator.append(resources["peak_accelerator_bytes"])
            control = case["control"]
            cancel_requested += int(control["cancel_requested"])
            cancel_acknowledged += int(control["cancel_acknowledged"])
            failure_injected += int(control["failure_injected"])
            crash_recovered += int(control["crash_recovered"])
            ready_segments_reused += control["ready_segments_reused"]
            ready_segment_outputs += len(case["output"]["ready_segment_sha256"])
            listening = case["listening"]
            listening_statuses[listening["status"]] += 1
            listening_verdicts[listening["verdict"]] += 1
            for defect_name, present in listening["defects"].items():
                if present:
                    defects[defect_name] += 1
        runs.append(
            {
                "run_id": run["run_id"],
                "benchmark_id": run["benchmark_id"],
                "work_package_id": run["work_package_id"],
                "status": run["status"],
                "execution_backend": run["model"]["execution_backend"],
                "model_revision": run["model"]["revision"],
                "exit_code": run["command"]["exit_code"],
                "case_statuses": ordered_counts(local_case_statuses, CASE_STATUSES),
            }
        )

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "source_schema_version": RESULT_SCHEMA_VERSION,
        "sources": sorted(sources, key=lambda item: (item["file_name"], item["sha256"])),
        "run_count": len(validated),
        "case_count": case_count,
        "run_statuses": ordered_counts(run_statuses, RUN_STATUSES),
        "case_statuses": ordered_counts(case_statuses, CASE_STATUSES),
        "performance": {
            "first_packet_ms": metric_summary(first_packet),
            "rtf": metric_summary(rtf),
            "peak_rss_bytes_max": max(peak_rss) if peak_rss else None,
            "peak_accelerator_bytes_max": max(peak_accelerator) if peak_accelerator else None,
        },
        "recovery": {
            "cancel_requested_cases": cancel_requested,
            "cancel_acknowledged_cases": cancel_acknowledged,
            "failure_injected_cases": failure_injected,
            "crash_recovered_cases": crash_recovered,
            "ready_segments_reused": ready_segments_reused,
            "ready_segment_outputs": ready_segment_outputs,
        },
        "listening": {
            "statuses": ordered_counts(listening_statuses, LISTENING_STATUSES),
            "verdicts": ordered_counts(listening_verdicts, LISTENING_VERDICTS),
            "defects": {key: defects[key] for key in DEFECT_KEYS if defects[key]},
        },
        "runs": sorted(runs, key=lambda item: (item["work_package_id"], item["run_id"])),
        "privacy": {
            "fixture_only": True,
            "contains_user_text": False,
            "contains_private_reference_audio": False,
            "evidence_contains_audio": False,
        },
    }


def display(value: object) -> str:
    return "—" if value is None else str(value)


def markdown_escape(value: object) -> str:
    return display(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(summary: dict[str, Any]) -> str:
    performance = summary["performance"]
    listening = summary["listening"]
    lines = [
        "# MOSS-TTS 基准摘要",
        "",
        f"- 摘要契约：`{summary['schema_version']}`",
        f"- 输入契约：`{summary['source_schema_version']}`",
        f"- 运行数：{summary['run_count']}；用例数：{summary['case_count']}",
        "- 隐私边界：仅冻结 fixture；不含用户正文、私人参考音频或证据音频。",
        "",
        "## 状态",
        "",
        "| 范围 | 状态计数 |",
        "| --- | --- |",
        f"| 运行 | `{json.dumps(summary['run_statuses'], ensure_ascii=False, sort_keys=True)}` |",
        f"| 用例 | `{json.dumps(summary['case_statuses'], ensure_ascii=False, sort_keys=True)}` |",
        "",
        "## 性能",
        "",
        "| 指标 | 样本数 | 中位数 | P95 | 最大值 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, key in (("首包（ms）", "first_packet_ms"), ("RTF", "rtf")):
        metric = performance[key]
        lines.append(
            f"| {label} | {metric['count']} | {display(metric['median'])} | "
            f"{display(metric['p95'])} | {display(metric['max'])} |"
        )
    lines.extend(
        [
            f"| 峰值 RSS（bytes） | — | — | — | {display(performance['peak_rss_bytes_max'])} |",
            "| 峰值加速器内存（bytes） | — | — | — | "
            f"{display(performance['peak_accelerator_bytes_max'])} |",
            "",
            "## 人工听检与恢复",
            "",
            f"- 听检状态：`{json.dumps(listening['statuses'], ensure_ascii=False, sort_keys=True)}`",
            f"- 听检结论：`{json.dumps(listening['verdicts'], ensure_ascii=False, sort_keys=True)}`",
            f"- 缺陷计数：`{json.dumps(listening['defects'], ensure_ascii=False, sort_keys=True)}`",
            f"- 恢复计数：`{json.dumps(summary['recovery'], ensure_ascii=False, sort_keys=True)}`",
            "",
            "## 运行明细",
            "",
            "| 工作包 | Run ID | 基准 | 状态 | 后端 | 模型 revision | 退出码 | 用例状态 |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |",
        ]
    )
    for run in summary["runs"]:
        lines.append(
            "| "
            + " | ".join(
                markdown_escape(value)
                for value in (
                    run["work_package_id"],
                    run["run_id"],
                    run["benchmark_id"],
                    run["status"],
                    run["execution_backend"],
                    run["model_revision"],
                    run["exit_code"],
                    json.dumps(run["case_statuses"], ensure_ascii=False, sort_keys=True),
                )
            )
            + " |"
        )
    lines.extend(["", "## 输入文件", ""])
    for source in summary["sources"]:
        lines.append(f"- `{source['file_name']}` — `{source['sha256']}`")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metrics", type=Path, nargs="+", help="benchmark result JSON files")
    parser.add_argument("--markdown-output", type=Path, help="write a Markdown summary")
    parser.add_argument("--json-output", type=Path, help="write a JSON summary")
    parser.add_argument(
        "--stdout-format",
        choices=("markdown", "json"),
        default="markdown",
        help="format used on stdout when no output path is supplied (default: %(default)s)",
    )
    parser.add_argument("--compact-json", action="store_true", help="do not indent JSON output")
    return parser.parse_args(argv)


def ensure_distinct_paths(args: argparse.Namespace) -> None:
    inputs = {input_path.resolve() for input_path in args.metrics}
    outputs = [path.resolve() for path in (args.markdown_output, args.json_output) if path]
    if len(outputs) != len(set(outputs)):
        raise OSError("Markdown and JSON outputs must use different paths")
    if any(output in inputs for output in outputs):
        raise OSError("report output must not overwrite an input metrics file")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ensure_distinct_paths(args)
        validated: list[tuple[Path, str, dict[str, Any]]] = []
        for metrics_path in args.metrics:
            source_hash = sha256_file(metrics_path)
            try:
                payload = json.loads(metrics_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise ContractValidationError(
                    [f"{metrics_path.name}: invalid JSON at line {error.lineno}, column {error.colno}"]
                ) from error
            validated.append(
                (metrics_path, source_hash, validate_result(payload, metrics_path.name))
            )
        summary = build_summary(validated)
        markdown = render_markdown(summary)
        json_summary = json.dumps(
            summary,
            ensure_ascii=False,
            indent=None if args.compact_json else 2,
            sort_keys=True,
        ) + "\n"
        if args.markdown_output:
            args.markdown_output.write_text(markdown, encoding="utf-8")
        if args.json_output:
            args.json_output.write_text(json_summary, encoding="utf-8")
        if not args.markdown_output and not args.json_output:
            sys.stdout.write(markdown if args.stdout_format == "markdown" else json_summary)
        return 0
    except ContractValidationError as error:
        print(
            json.dumps(
                {
                    "schema_version": SUMMARY_SCHEMA_VERSION,
                    "status": "schema_error",
                    "errors": error.errors,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except (OSError, TypeError) as error:
        print(
            json.dumps(
                {
                    "schema_version": SUMMARY_SCHEMA_VERSION,
                    "status": "io_error",
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
