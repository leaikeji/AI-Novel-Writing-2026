from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).with_name("mps_probe.py")
SPEC = importlib.util.spec_from_file_location("vg40_mps_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


def successful_operations():
    return [
        PROBE.OperationResult(
            name,
            True,
            "torch.bfloat16",
            "mps:0",
            None,
            None,
        )
        for name in sorted(PROBE.EXPECTED_OPERATION_NAMES)
    ]


def test_payload_requires_every_frozen_gate(monkeypatch) -> None:
    monkeypatch.setattr(PROBE.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(PROBE.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")
    operations = successful_operations()

    payload = PROBE.build_payload(
        versions=dict(PROBE.EXPECTED_VERSIONS),
        mps_built=True,
        mps_available=True,
        operations=operations,
    )

    assert payload["passed"] is True


def test_payload_fails_closed_on_version_or_operation_drift(monkeypatch) -> None:
    monkeypatch.setattr(PROBE.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(PROBE.platform, "machine", lambda: "arm64")
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "0")

    version_drift = PROBE.build_payload(
        versions={**PROBE.EXPECTED_VERSIONS, "torch": "2.9.0"},
        mps_built=True,
        mps_available=True,
        operations=successful_operations(),
    )
    operation_failure = PROBE.build_payload(
        versions=dict(PROBE.EXPECTED_VERSIONS),
        mps_built=True,
        mps_available=True,
        operations=[
            *successful_operations()[:-1],
            PROBE.OperationResult(
                sorted(PROBE.EXPECTED_OPERATION_NAMES)[-1],
                False,
                None,
                None,
                "RuntimeError",
                "VG40_T1_OPERATOR_UNSUPPORTED",
            ),
        ],
    )

    assert version_drift["passed"] is False
    assert operation_failure["passed"] is False


def test_payload_rejects_missing_fallback_fence(monkeypatch) -> None:
    monkeypatch.setattr(PROBE.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(PROBE.platform, "machine", lambda: "arm64")
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

    payload = PROBE.build_payload(
        versions=dict(PROBE.EXPECTED_VERSIONS),
        mps_built=True,
        mps_available=True,
        operations=successful_operations(),
    )

    assert payload["passed"] is False
