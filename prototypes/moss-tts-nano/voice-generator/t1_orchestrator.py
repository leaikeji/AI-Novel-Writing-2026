"""Fail-closed T1 assessment and evidence helpers for Plan 40.

This module contains no Torch dependency and cannot start a process by itself.
The serial spike launcher supplies 15 host baselines, a watchdog result, and the
bounded output of ``mps_probe.py``.  Keeping classification here makes it
testable without weakening the watchdog or importing model code in PawApp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping, Sequence

from macos_memory_watchdog import (
    GIB,
    MemoryPressure,
    MetricSnapshot,
    ProcessOutcome,
    StopReason,
    WatchdogResult,
)


EXPECTED_PROBE_SCHEMA = "vg40-mps-probe/1"
EXPECTED_OPERATIONS = frozenset(
    {
        "bf16_arithmetic",
        "embedding",
        "rms_norm",
        "rotary_and_mask",
        "scaled_dot_product_attention",
        "top_k_top_p_multinomial",
    }
)


class T1Verdict(str, Enum):
    PASS = "PASS"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class T1Assessment:
    verdict: T1Verdict
    reason_code: str
    probe_started: bool
    minimum_available_bytes: int | None
    sample_count: int

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["verdict"] = self.verdict.value
        return payload


def assess_preflight(
    samples: Sequence[MetricSnapshot], *, minimum_available_bytes: int = 4 * GIB
) -> T1Assessment:
    if len(samples) != 15:
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_EVIDENCE_INCOMPLETE",
            False,
            min((item.available_memory_estimate_bytes for item in samples), default=None),
            len(samples),
        )
    minimum_available = min(item.available_memory_estimate_bytes for item in samples)
    if any(item.nano_model_loaded for item in samples):
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_NANO_RESIDENCY_CONFLICT",
            False,
            minimum_available,
            len(samples),
        )
    if any(item.memory_pressure is MemoryPressure.UNKNOWN for item in samples):
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_MEASUREMENT_UNAVAILABLE",
            False,
            minimum_available,
            len(samples),
        )
    if any(item.memory_pressure is MemoryPressure.CRITICAL for item in samples):
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_PREFLIGHT_MEMORY_PRESSURE_CRITICAL",
            False,
            minimum_available,
            len(samples),
        )
    if minimum_available < minimum_available_bytes:
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_PREFLIGHT_HEADROOM_INSUFFICIENT",
            False,
            minimum_available,
            len(samples),
        )
    return T1Assessment(
        T1Verdict.PASS,
        "VG40_T1_PREFLIGHT_READY",
        False,
        minimum_available,
        len(samples),
    )


def assess_probe(
    baseline_samples: Sequence[MetricSnapshot],
    watchdog_result: WatchdogResult,
    probe_payload: Mapping[str, object] | None,
    minimum_available_bytes: int = 4 * GIB,
) -> T1Assessment:
    preflight = assess_preflight(
        baseline_samples, minimum_available_bytes=minimum_available_bytes
    )
    if preflight.verdict is not T1Verdict.PASS:
        return preflight
    if watchdog_result.stop_reason in {
        StopReason.CRITICAL_MEMORY_PRESSURE,
        StopReason.HEADROOM_BELOW_ABORT_FLOOR,
        StopReason.SWAP_BUDGET_EXCEEDED,
        StopReason.PAGEOUT_BUDGET_EXCEEDED,
        StopReason.PREFLIGHT_HEADROOM_INSUFFICIENT,
    }:
        return T1Assessment(
            T1Verdict.BLOCKED,
            "VG40_T1_MEMORY_ABORTED",
            _probe_started(watchdog_result),
            preflight.minimum_available_bytes,
            len(baseline_samples),
        )
    if watchdog_result.stop_reason in {
        StopReason.MEASUREMENT_UNAVAILABLE,
        StopReason.NANO_RELOADED,
    }:
        return T1Assessment(
            T1Verdict.HOLD,
            "VG40_T1_MEASUREMENT_UNAVAILABLE",
            _probe_started(watchdog_result),
            preflight.minimum_available_bytes,
            len(baseline_samples),
        )
    if (
        watchdog_result.outcome is not ProcessOutcome.COMPLETED
        or not watchdog_result.safe_for_this_run
    ):
        return T1Assessment(
            T1Verdict.BLOCKED,
            "VG40_T1_RUNTIME_UNSUPPORTED",
            _probe_started(watchdog_result),
            preflight.minimum_available_bytes,
            len(baseline_samples),
        )
    if not _valid_probe_payload(probe_payload):
        return T1Assessment(
            T1Verdict.BLOCKED,
            "VG40_T1_MPS_UNSUPPORTED",
            True,
            preflight.minimum_available_bytes,
            len(baseline_samples),
        )
    return T1Assessment(
        T1Verdict.PASS,
        "VG40_T1_PASS",
        True,
        preflight.minimum_available_bytes,
        len(baseline_samples),
    )


def load_probe_payload(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("probe output must be a regular non-symlink file")
    if path.stat().st_size <= 0 or path.stat().st_size > 64 * 1024:
        raise ValueError("probe output size is outside the fixed bound")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("probe output must be a JSON object")
    return payload


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists():
        raise FileExistsError("evidence file already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_path, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary_path.unlink(missing_ok=True)


def _probe_started(result: WatchdogResult) -> bool:
    return any(event.kind == "child_started" for event in result.events)


def _valid_probe_payload(payload: Mapping[str, object] | None) -> bool:
    if payload is None:
        return False
    if payload.get("schema_version") != EXPECTED_PROBE_SCHEMA:
        return False
    if payload.get("passed") is not True:
        return False
    if payload.get("version_match") is not True:
        return False
    if payload.get("fallback_disabled") is not True:
        return False
    if payload.get("mps_built") is not True or payload.get("mps_available") is not True:
        return False
    operations = payload.get("operations")
    if not isinstance(operations, list):
        return False
    names: set[str] = set()
    for item in operations:
        if not isinstance(item, dict) or item.get("passed") is not True:
            return False
        name = item.get("name")
        if not isinstance(name, str):
            return False
        names.add(name)
    return names == EXPECTED_OPERATIONS
