#!/usr/bin/env python3
"""Verify the PawApp lifecycle owner against a real private Sidecar.

This gate prints only the public, secret-free lifecycle snapshot.  The caller
must provide the same fixed environment contract used by the PawApp runtime.
"""

from __future__ import annotations

import asyncio
import json
import sys

from backend.narration.contracts import AdapterHealthStatus
from backend.narration.pawapp_runtime import (
    get_ready_narration_adapter,
    launch_narration_runtime,
    narration_runtime_status,
    stop_narration_runtime,
    wait_narration_runtime_initialized,
)


async def _verify() -> dict[str, object]:
    adapter = None
    ready: dict[str, object] | None = None
    renewed: int | None = None
    try:
        await launch_narration_runtime()
        await wait_narration_runtime_initialized(timeout_seconds=180)
        ready = narration_runtime_status()
        if not (
            ready.get("technical_enabled") is True
            and ready.get("lifecycle_status") == "ready"
            and ready.get("model_ready") is True
            and ready.get("product_visible") is False
        ):
            raise RuntimeError("PAWAPP_RUNTIME_NOT_READY")
        adapter = get_ready_narration_adapter()
        if adapter is None:
            raise RuntimeError("PAWAPP_READY_ADAPTER_MISSING")
        renewed = await adapter.renew_lease()
        if renewed != ready.get("lease_generation"):
            raise RuntimeError("PAWAPP_LEASE_GENERATION_CHANGED")
    finally:
        await stop_narration_runtime()

    stopped = narration_runtime_status()
    if (
        stopped.get("lifecycle_status") != "disabled"
        or stopped.get("product_visible") is not False
    ):
        raise RuntimeError("PAWAPP_RUNTIME_NOT_DISABLED_AFTER_STOP")
    if adapter is None or ready is None or renewed is None:
        raise RuntimeError("PAWAPP_RUNTIME_EVIDENCE_INCOMPLETE")
    inactive = await adapter.health()
    if not (
        inactive.status is AdapterHealthStatus.UNAVAILABLE
        and inactive.reason_code == "WORKER_LEASE_INACTIVE"
    ):
        raise RuntimeError("PAWAPP_ADAPTER_NOT_INERT_AFTER_STOP")
    return {
        "schema_version": "t1-pawapp-runtime-real/1",
        "status": "passed",
        "protocol_version": ready["protocol_version"],
        "worker_generation": ready["worker_generation"],
        "lease_generation": ready["lease_generation"],
        "manual_renew_generation": renewed,
        "model_fingerprint_sha256": ready["model_fingerprint_sha256"],
        "product_visible": ready["product_visible"],
        "after_stop": stopped["lifecycle_status"],
        "after_stop_adapter_health": inactive.status.value,
        "after_stop_reason_code": inactive.reason_code,
        "secrets_recorded": False,
        "text_recorded": False,
        "audio_bytes_recorded": False,
    }


def main() -> int:
    try:
        result = asyncio.run(_verify())
    except Exception as error:  # output-safe gate boundary
        print(
            json.dumps(
                {
                    "schema_version": "t1-pawapp-runtime-real/1",
                    "status": "failed",
                    "failure_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
