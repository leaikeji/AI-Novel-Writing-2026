"""Load the fixed VoiceGenerator on MPS and intentionally die after load.

This child exists only for Plan 40 crash-recovery evidence.  It never performs
generation and never publishes a voice/token/audio asset.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import signal
from typing import Sequence


SCHEMA = "vg40-t5-crash-phase/1"
REVISION = re.compile(r"^[0-9a-f]{40}$")


def _write_phase(path: Path, revision: str) -> None:
    payload = {
        "schema_version": SCHEMA,
        "phase": "generator_loaded_before_injected_sigkill",
        "revision": revision,
        "pid": os.getpid(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--phase-marker", type=Path, required=True)
    parser.add_argument("--mps-memory-fraction", type=float, default=0.65)
    arguments = parser.parse_args(argv)

    if REVISION.fullmatch(arguments.revision) is None:
        raise ValueError("revision must be a fixed commit")
    if arguments.model_dir.is_symlink() or not arguments.model_dir.is_dir():
        raise ValueError("model directory is invalid")
    if arguments.model_dir.absolute() != arguments.model_dir.resolve(strict=True):
        raise ValueError("model directory traverses a symlink")
    if arguments.phase_marker.exists() or arguments.phase_marker.is_symlink():
        raise ValueError("phase marker already exists")
    if not arguments.phase_marker.is_absolute() or not arguments.phase_marker.parent.is_dir():
        raise ValueError("phase marker parent is invalid")
    required_environment = {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PYTORCH_ENABLE_MPS_FALLBACK": "0",
    }
    if any(os.environ.get(key) != value for key, value in required_environment.items()):
        raise RuntimeError("offline or fallback environment is not frozen")

    import torch
    from transformers import AutoModel

    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable")
    torch.set_grad_enabled(False)
    torch.mps.set_per_process_memory_fraction(arguments.mps_memory_fraction)
    model = AutoModel.from_pretrained(
        arguments.model_dir,
        trust_remote_code=True,
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        device_map={"": "mps"},
        attn_implementation="sdpa",
    ).eval()
    torch.mps.synchronize()
    if {str(parameter.device) for parameter in model.parameters()} != {"mps:0"}:
        raise RuntimeError("generator was not fully loaded on MPS")
    _write_phase(arguments.phase_marker, arguments.revision)
    os.kill(os.getpid(), signal.SIGKILL)
    return 99


if __name__ == "__main__":
    raise SystemExit(main())
