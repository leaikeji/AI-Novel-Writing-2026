"""One-shot, offline T2 loader for one fixed MOSS model component.

The process intentionally loads no processor and performs no generation.  A
parent watchdog owns lifecycle and host telemetry.  This child writes only a
bounded, atomic result without exception messages or model paths.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gc
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Sequence


SCHEMA = "vg40-t2-load-probe/1"
REVISION = re.compile(r"^[0-9a-f]{40}$")
COMPONENTS = {"voice-generator", "audio-tokenizer"}
REQUIRED_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "PYTORCH_ENABLE_MPS_FALLBACK": "0",
}


class T2ProbeError(RuntimeError):
    pass


def validate_probe_request(
    *, component: str, model_dir: Path, revision: str, result_path: Path
) -> dict[str, object]:
    if component not in COMPONENTS:
        raise T2ProbeError("component is outside the fixed allowlist")
    if REVISION.fullmatch(revision) is None:
        raise T2ProbeError("revision is not a fixed commit")
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise T2ProbeError("model directory must be a regular directory")
    resolved_model = model_dir.resolve(strict=True)
    if model_dir.absolute() != resolved_model:
        raise T2ProbeError("model directory traverses a symlink")
    config_path = model_dir / "config.json"
    if config_path.is_symlink() or not config_path.is_file():
        raise T2ProbeError("model config is missing")
    weight_files = sorted(model_dir.glob("*.safetensors"))
    if not weight_files or any(
        path.is_symlink() or not path.is_file() or path.stat().st_size <= 0
        for path in weight_files
    ):
        raise T2ProbeError("verified safetensors weights are missing")
    if result_path.exists() or result_path.is_symlink():
        raise T2ProbeError("result path must not exist")
    if not result_path.is_absolute() or not result_path.parent.is_dir():
        raise T2ProbeError("result parent must be an existing absolute directory")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("auto_map"), dict):
        raise T2ProbeError("model config lacks the audited AutoModel mapping")
    if not isinstance(config["auto_map"].get("AutoModel"), str):
        raise T2ProbeError("model config AutoModel mapping is invalid")
    return {
        "component": component,
        "revision": revision,
        "model_type": config.get("model_type"),
        "weight_file_count": len(weight_files),
        "weight_bytes": sum(path.stat().st_size for path in weight_files),
    }


def run_probe(
    *,
    component: str,
    model_dir: Path,
    revision: str,
    result_path: Path,
    mps_memory_fraction: float,
    stabilize_seconds: float,
) -> int:
    identity: dict[str, object] = {
        "component": component,
        "revision": revision,
    }
    try:
        identity = validate_probe_request(
            component=component,
            model_dir=model_dir,
            revision=revision,
            result_path=result_path,
        )
        _validate_environment()
        if not 0.05 <= mps_memory_fraction <= 1.0:
            raise T2ProbeError("MPS memory fraction is outside the spike bound")
        if not 0.0 <= stabilize_seconds <= 60.0:
            raise T2ProbeError("stabilization interval is outside the spike bound")

        import torch
        from transformers import AutoModel

        if not torch.backends.mps.is_built() or not torch.backends.mps.is_available():
            raise T2ProbeError("MPS is unavailable")
        torch.set_grad_enabled(False)
        torch.mps.set_per_process_memory_fraction(mps_memory_fraction)
        load_arguments: dict[str, object] = {
            "trust_remote_code": True,
            "local_files_only": True,
            "dtype": torch.bfloat16,
            "low_cpu_mem_usage": True,
            "device_map": {"": "mps"},
        }
        if component == "voice-generator":
            load_arguments["attn_implementation"] = "sdpa"

        load_started = time.monotonic()
        model = AutoModel.from_pretrained(model_dir, **load_arguments)
        torch.mps.synchronize()
        load_seconds = time.monotonic() - load_started
        model.eval()
        parameters = tuple(model.parameters())
        devices = sorted({str(parameter.device) for parameter in parameters})
        dtypes = sorted({str(parameter.dtype) for parameter in parameters})
        if not parameters or devices != ["mps:0"] or dtypes != ["torch.bfloat16"]:
            raise T2ProbeError("loaded parameter placement did not match MPS/BF16")
        if stabilize_seconds:
            time.sleep(stabilize_seconds)
            torch.mps.synchronize()
        payload = {
            "schema_version": SCHEMA,
            "passed": True,
            **identity,
            "requested_device": "mps",
            "actual_parameter_devices": devices,
            "requested_dtype": "bfloat16",
            "actual_parameter_dtypes": dtypes,
            "parameter_count": sum(parameter.numel() for parameter in parameters),
            "parameter_bytes": sum(
                parameter.numel() * parameter.element_size() for parameter in parameters
            ),
            "mps_memory_fraction": mps_memory_fraction,
            "mps_current_allocated_bytes": torch.mps.current_allocated_memory(),
            "mps_driver_allocated_bytes": torch.mps.driver_allocated_memory(),
            "load_seconds": load_seconds,
            "stabilize_seconds": stabilize_seconds,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        del parameters
        del model
        gc.collect()
        torch.mps.empty_cache()
        torch.mps.synchronize()
        payload["mps_allocated_after_release_bytes"] = torch.mps.current_allocated_memory()
        _write_result(result_path, payload)
        return 0
    except BaseException as error:
        payload = {
            "schema_version": SCHEMA,
            "passed": False,
            **identity,
            "error_type": type(error).__name__,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            _write_result(result_path, payload)
        except BaseException:
            pass
        return 1


def _validate_environment() -> None:
    for name, expected in REQUIRED_ENVIRONMENT.items():
        if os.environ.get(name) != expected:
            raise T2ProbeError("offline or fallback environment is not frozen")


def _write_result(path: Path, payload: dict[str, object]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise T2ProbeError("probe result exceeded the fixed bound")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError("probe result already exists")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=sorted(COMPONENTS), required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--mps-memory-fraction", type=float, default=0.55)
    parser.add_argument("--stabilize-seconds", type=float, default=10.0)
    arguments = parser.parse_args(argv)
    return run_probe(
        component=arguments.component,
        model_dir=arguments.model_dir,
        revision=arguments.revision,
        result_path=arguments.result,
        mps_memory_fraction=arguments.mps_memory_fraction,
        stabilize_seconds=arguments.stabilize_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
