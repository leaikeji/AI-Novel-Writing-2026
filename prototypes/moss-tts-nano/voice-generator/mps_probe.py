"""Bounded, weight-free Apple MPS/BF16 probe for Plan 40 T1.

The probe imports only the isolated runtime dependencies and executes a small
allowlist of tensor operations used by the fixed MOSS VoiceGenerator path.  It
does not resolve a model repository, load weights, generate audio, or accept
arbitrary code.  The launcher must set ``PYTORCH_ENABLE_MPS_FALLBACK=0``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from typing import Callable


EXPECTED_VERSIONS = {
    "torch": "2.9.1",
    "torchaudio": "2.9.1",
    "transformers": "5.0.0",
}

EXPECTED_OPERATION_NAMES = frozenset(
    {
        "bf16_arithmetic",
        "embedding",
        "rms_norm",
        "rotary_and_mask",
        "scaled_dot_product_attention",
        "top_k_top_p_multinomial",
    }
)
MPS_MEMORY_FRACTION = 0.05


@dataclass(frozen=True)
class OperationResult:
    name: str
    passed: bool
    dtype: str | None
    device: str | None
    error_type: str | None
    reason_code: str | None


def build_payload(
    *,
    versions: dict[str, str],
    mps_built: bool,
    mps_available: bool,
    mps_recommended_max_bytes: int | None = None,
    operations: list[OperationResult],
) -> dict[str, object]:
    version_match = versions == EXPECTED_VERSIONS
    platform_ok = platform.system() == "Darwin" and platform.machine() == "arm64"
    fallback_disabled = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "0"
    operation_names = {item.name for item in operations}
    passed = (
        version_match
        and platform_ok
        and fallback_disabled
        and mps_built
        and mps_available
        and operation_names == EXPECTED_OPERATION_NAMES
        and len(operations) == len(EXPECTED_OPERATION_NAMES)
        and all(item.passed for item in operations)
    )
    return {
        "schema_version": "vg40-mps-probe/1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "expected_versions": EXPECTED_VERSIONS,
        "versions": versions,
        "version_match": version_match,
        "fallback_disabled": fallback_disabled,
        "mps_built": mps_built,
        "mps_available": mps_available,
        "mps_memory_fraction": MPS_MEMORY_FRACTION,
        "mps_recommended_max_bytes": mps_recommended_max_bytes,
        "mps_allocator_limit_bytes": (
            int(mps_recommended_max_bytes * MPS_MEMORY_FRACTION)
            if mps_recommended_max_bytes is not None
            else None
        ),
        "operations": [asdict(item) for item in operations],
        "passed": passed,
    }


def _version(distribution: str) -> str:
    return importlib.metadata.version(distribution)


def _run_operation(name: str, operation: Callable[[], object], torch: object) -> OperationResult:
    try:
        value = operation()
        torch.mps.synchronize()  # type: ignore[attr-defined]
        if not hasattr(value, "device") or str(value.device) != "mps:0":
            raise RuntimeError("operation result left the MPS device")
        if hasattr(value, "is_floating_point") and value.is_floating_point():
            finite = bool(torch.isfinite(value).all().item())  # type: ignore[attr-defined]
            if not finite:
                raise RuntimeError("operation produced non-finite values")
        return OperationResult(
            name=name,
            passed=True,
            dtype=str(getattr(value, "dtype", "unknown")),
            device=str(value.device),
            error_type=None,
            reason_code=None,
        )
    except BaseException as error:
        return OperationResult(
            name=name,
            passed=False,
            dtype=None,
            device=None,
            error_type=type(error).__name__,
            reason_code="VG40_T1_OPERATOR_UNSUPPORTED",
        )


def run_probe() -> dict[str, object]:
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") != "0":
        raise RuntimeError("PYTORCH_ENABLE_MPS_FALLBACK must be exactly 0")
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        raise RuntimeError("HF_HUB_OFFLINE must be exactly 1")
    if os.environ.get("TRANSFORMERS_OFFLINE") != "1":
        raise RuntimeError("TRANSFORMERS_OFFLINE must be exactly 1")

    import torch
    import torchaudio  # noqa: F401 - import compatibility is part of T1.
    import transformers  # noqa: F401 - import compatibility is part of T1.
    import torch.nn.functional as functional

    versions = {name: _version(name) for name in EXPECTED_VERSIONS}
    mps_built = bool(torch.backends.mps.is_built())
    mps_available = bool(torch.backends.mps.is_available())
    if not mps_built or not mps_available:
        return build_payload(
            versions=versions,
            mps_built=mps_built,
            mps_available=mps_available,
            mps_recommended_max_bytes=None,
            operations=[],
        )

    recommended_max_bytes = int(torch.mps.recommended_max_memory())
    torch.mps.set_per_process_memory_fraction(MPS_MEMORY_FRACTION)
    device = torch.device("mps")
    generator = torch.Generator(device=device).manual_seed(40)

    def bf16_arithmetic() -> object:
        value = torch.arange(64, device=device, dtype=torch.bfloat16).reshape(2, 32)
        return value * torch.tensor(0.5, device=device, dtype=torch.bfloat16)

    def embedding() -> object:
        weight = torch.randn(128, 64, device=device, dtype=torch.bfloat16)
        indices = torch.tensor([[1, 7, 31]], device=device, dtype=torch.int64)
        return functional.embedding(indices, weight)

    def rms_norm() -> object:
        value = torch.randn(2, 8, 64, device=device, dtype=torch.bfloat16)
        weight = torch.ones(64, device=device, dtype=torch.bfloat16)
        return functional.rms_norm(value, (64,), weight, eps=1e-6)

    def rotary_and_mask() -> object:
        value = torch.randn(2, 8, 64, device=device, dtype=torch.bfloat16)
        positions = torch.arange(8, device=device, dtype=torch.float32)
        angles = positions[:, None] / torch.pow(
            torch.tensor(10_000.0, device=device),
            torch.arange(0, 32, device=device, dtype=torch.float32) / 32,
        )
        rotated = value[..., :32] * torch.cos(angles).to(torch.bfloat16)
        mask = torch.triu(
            torch.full((8, 8), float("-inf"), device=device, dtype=torch.float32),
            diagonal=1,
        )
        mask_summary = torch.nan_to_num(mask, neginf=0).sum(dim=-1).to(torch.bfloat16)
        return rotated.mean(dim=-1) + mask_summary[None, :]

    def attention() -> object:
        query = torch.randn(1, 8, 16, 64, device=device, dtype=torch.bfloat16)
        key = torch.randn(1, 8, 16, 64, device=device, dtype=torch.bfloat16)
        value = torch.randn(1, 8, 16, 64, device=device, dtype=torch.bfloat16)
        return functional.scaled_dot_product_attention(
            query,
            key,
            value,
            is_causal=True,
        )

    def sampling() -> object:
        logits = torch.randn(4, 256, device=device, dtype=torch.float32)
        probabilities = torch.softmax(logits, dim=-1)
        top_values, top_indices = torch.topk(probabilities, 32, dim=-1)
        cumulative = torch.cumsum(top_values, dim=-1)
        retained = torch.where(cumulative <= 0.95, top_values, torch.zeros_like(top_values))
        retained[..., 0] = top_values[..., 0]
        retained = retained / retained.sum(dim=-1, keepdim=True)
        selected = torch.multinomial(retained, 1, generator=generator)
        return torch.gather(top_indices, 1, selected)

    operations = [
        _run_operation("bf16_arithmetic", bf16_arithmetic, torch),
        _run_operation("embedding", embedding, torch),
        _run_operation("rms_norm", rms_norm, torch),
        _run_operation("rotary_and_mask", rotary_and_mask, torch),
        _run_operation("scaled_dot_product_attention", attention, torch),
        _run_operation("top_k_top_p_multinomial", sampling, torch),
    ]
    return build_payload(
        versions=versions,
        mps_built=mps_built,
        mps_available=mps_available,
        mps_recommended_max_bytes=recommended_max_bytes,
        operations=operations,
    )


def _atomic_write_payload(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError("probe output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ValueError("probe output exceeded the fixed bound")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        payload = run_probe()
    except Exception as error:
        payload = {
            "schema_version": "vg40-mps-probe/1",
            "passed": False,
            "error_type": type(error).__name__,
            "reason_code": "VG40_T1_PROBE_FAILED",
        }
    if arguments.output is not None:
        try:
            _atomic_write_payload(arguments.output, payload)
        except Exception as error:
            payload = {
                "schema_version": "vg40-mps-probe/1",
                "passed": False,
                "error_type": type(error).__name__,
                "reason_code": "VG40_T1_EVIDENCE_COMMIT_FAILED",
            }
    sys.stdout.write(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    )
    return 0 if payload.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
