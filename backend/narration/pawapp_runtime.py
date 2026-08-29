"""Fail-closed PawApp lifecycle owner for the private MOSS Sidecar.

Importing this module does not read the bootstrap secret, access the network,
or start a model.  Only the explicit QwenPaw startup hook calls ``launch``;
the default-disabled path returns before the runtime factory reads a token.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, replace
import os
import re
from typing import Callable, Mapping

from .contracts import AdapterHealth, AdapterHealthStatus, ContractError
from .runtime import (
    PROTOCOL_VERSION,
    WORKER_LEASE_RENEW_INTERVAL_SECONDS,
    SidecarMossNanoTTSAdapter,
    SidecarRuntimeError,
    build_moss_adapter_from_environment,
)


PRODUCT_ENABLE_ENV = "AI_NOVEL_TTS_PRODUCT_ENABLED"
IDLE_UNLOAD_SECONDS_ENV = "AI_NOVEL_TTS_IDLE_UNLOAD_SECONDS"
DEFAULT_IDLE_UNLOAD_SECONDS = 300
MIN_IDLE_UNLOAD_SECONDS = 60
MAX_IDLE_UNLOAD_SECONDS = 3600
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,95}$")
RuntimeFactory = Callable[
    [Mapping[str, str] | None],
    SidecarMossNanoTTSAdapter | None,
]


@dataclass(frozen=True, slots=True)
class NarrationRuntimeSnapshot:
    technical_enabled: bool = False
    lifecycle_status: str = "disabled"
    sidecar_reachable: bool = False
    model_ready: bool = False
    model_loaded: bool = False
    product_visible: bool = False
    idle_unload_seconds: int | None = None
    protocol_version: str = PROTOCOL_VERSION
    worker_generation: int | None = None
    lease_generation: int | None = None
    model_fingerprint_sha256: str | None = None
    reason_code: str | None = None

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


_lifecycle_lock = asyncio.Lock()
_adapter: SidecarMossNanoTTSAdapter | None = None
_runtime_task: asyncio.Task[None] | None = None
_snapshot = NarrationRuntimeSnapshot()


def _safe_reason(error: BaseException, fallback: str) -> str:
    code = getattr(error, "code", None)
    return code if isinstance(code, str) and _REASON_CODE.fullmatch(code) else fallback


def narration_runtime_status() -> dict[str, object]:
    """Return a secret-free, network-free status snapshot for `/health`."""

    return _snapshot.public_dict()


def get_ready_narration_adapter() -> SidecarMossNanoTTSAdapter | None:
    """Internal worker dependency; no user-visible capability is implied."""

    if _snapshot.lifecycle_status != "ready" or not _snapshot.model_ready:
        return None
    return _adapter


def _idle_unload_seconds(values: Mapping[str, str]) -> int:
    raw = values.get(IDLE_UNLOAD_SECONDS_ENV, str(DEFAULT_IDLE_UNLOAD_SECONDS))
    if re.fullmatch(r"[0-9]+", raw) is None:
        raise ContractError("TTS idle unload duration must be a decimal integer")
    seconds = int(raw)
    if not MIN_IDLE_UNLOAD_SECONDS <= seconds <= MAX_IDLE_UNLOAD_SECONDS:
        raise ContractError("TTS idle unload duration is outside the safe bounds")
    return seconds


async def _update_if_current(
    adapter: SidecarMossNanoTTSAdapter,
    snapshot: NarrationRuntimeSnapshot,
) -> bool:
    global _snapshot
    async with _lifecycle_lock:
        if _adapter is not adapter:
            return False
        _snapshot = snapshot
        return True


async def _warmup_with_lease_renewal(
    adapter: SidecarMossNanoTTSAdapter,
    lease_generation: int,
) -> tuple[AdapterHealth, int]:
    """Keep the short worker lease alive while one long warmup is in flight."""

    warmup_task = asyncio.create_task(
        adapter.warmup(),
        name="ai-novel-moss-tts-warmup",
    )
    try:
        while True:
            done, _ = await asyncio.wait(
                {warmup_task},
                timeout=WORKER_LEASE_RENEW_INTERVAL_SECONDS,
            )
            if warmup_task in done:
                return await warmup_task, lease_generation
            lease_generation = await adapter.renew_lease()
    finally:
        if not warmup_task.done():
            warmup_task.cancel()
        try:
            await warmup_task
        except asyncio.CancelledError:
            pass
        except (ContractError, SidecarRuntimeError, OSError, TimeoutError):
            # The normal completion branch already propagates warmup errors.
            # If lease renewal failed first, drain the child without replacing
            # that authoritative lifecycle error or leaking a task exception.
            pass


async def _run_runtime(
    adapter: SidecarMossNanoTTSAdapter,
    *,
    product_visible_requested: bool,
    lazy_load_requested: bool,
    idle_unload_seconds: int,
) -> None:
    global _adapter, _runtime_task, _snapshot
    try:
        lease_generation = await adapter.activate()
        health = await adapter.health()
        if health.status is AdapterHealthStatus.UNAVAILABLE:
            raise SidecarRuntimeError(
                health.reason_code or "SIDECAR_UNAVAILABLE",
                "Sidecar health is unavailable",
            )
        enable_on_demand = getattr(adapter, "enable_on_demand_warmup", None)
        release_if_idle = getattr(adapter, "release_model_if_idle", None)
        expected_fingerprint_sha256 = getattr(
            adapter,
            "expected_model_fingerprint_sha256",
            None,
        )
        lazy_load = (
            lazy_load_requested
            and callable(enable_on_demand)
            and callable(release_if_idle)
            and isinstance(expected_fingerprint_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint_sha256)
            is not None
        )
        if lazy_load:
            enable_on_demand()
            model_fingerprint_sha256 = (
                health.model_fingerprint_sha256
                or expected_fingerprint_sha256
            )
            model_loaded = health.status is AdapterHealthStatus.HEALTHY
        else:
            warmed, lease_generation = await _warmup_with_lease_renewal(
                adapter,
                lease_generation,
            )
            if warmed.status is not AdapterHealthStatus.HEALTHY:
                raise SidecarRuntimeError(
                    warmed.reason_code or "SIDECAR_WARMUP_UNAVAILABLE",
                    "Sidecar warmup is unavailable",
                )
            model_fingerprint_sha256 = warmed.model_fingerprint_sha256
            model_loaded = True
        ready = NarrationRuntimeSnapshot(
            technical_enabled=True,
            lifecycle_status="ready",
            sidecar_reachable=True,
            # In on-demand mode this means the frozen adapter can satisfy a
            # request on demand; ``model_loaded`` reports actual residency.
            model_ready=True,
            model_loaded=model_loaded,
            product_visible=product_visible_requested,
            idle_unload_seconds=(idle_unload_seconds if lazy_load else None),
            worker_generation=adapter.worker_generation,
            lease_generation=lease_generation,
            model_fingerprint_sha256=model_fingerprint_sha256,
        )
        if not await _update_if_current(adapter, ready):
            await adapter.deactivate()
            return
        while True:
            await asyncio.sleep(WORKER_LEASE_RENEW_INTERVAL_SECONDS)
            lease_generation = await adapter.renew_lease()
            if lazy_load:
                enable_on_demand()
                await release_if_idle(idle_unload_seconds)
                enable_on_demand()
                current_lease_generation = getattr(
                    adapter,
                    "lease_generation",
                    lease_generation,
                )
                if isinstance(current_lease_generation, int):
                    lease_generation = current_lease_generation
            renewed = replace(
                ready,
                worker_generation=adapter.worker_generation,
                lease_generation=lease_generation,
                model_loaded=(
                    bool(getattr(adapter, "model_loaded", False))
                    if lazy_load
                    else True
                ),
            )
            if not await _update_if_current(adapter, renewed):
                await adapter.deactivate()
                return
            ready = renewed
    except asyncio.CancelledError:
        raise
    except (ContractError, SidecarRuntimeError, OSError, TimeoutError) as error:
        reason_code = _safe_reason(error, "SIDECAR_LIFECYCLE_FAILED")
        await _update_if_current(
            adapter,
            NarrationRuntimeSnapshot(
                technical_enabled=True,
                lifecycle_status="unavailable",
                sidecar_reachable=False,
                model_ready=False,
                reason_code=reason_code,
            ),
        )
        try:
            await adapter.deactivate()
        except (SidecarRuntimeError, OSError, TimeoutError):
            # The Sidecar watchdog independently expires the short lease.
            pass
    finally:
        async with _lifecycle_lock:
            current_task = asyncio.current_task()
            if _runtime_task is current_task:
                _runtime_task = None
            if _adapter is adapter and _snapshot.lifecycle_status != "ready":
                _adapter = None


async def launch_narration_runtime(
    environ: Mapping[str, str] | None = None,
    *,
    factory: RuntimeFactory = build_moss_adapter_from_environment,
) -> None:
    """Start initialization in the background without delaying QwenPaw boot."""

    global _adapter, _runtime_task, _snapshot
    values = os.environ if environ is None else environ
    requested = values.get("AI_NOVEL_TTS_RUNTIME_ENABLED", "false") == "true"
    product_visible_requested = values.get(PRODUCT_ENABLE_ENV, "false") == "true"
    validation_requested = (
        values.get("AI_NOVEL_TTS_VALIDATION_ENABLED", "false") == "true"
    )
    async with _lifecycle_lock:
        if _runtime_task is not None or _adapter is not None:
            return
        try:
            idle_unload_seconds = (
                _idle_unload_seconds(values)
                if requested
                else DEFAULT_IDLE_UNLOAD_SECONDS
            )
            adapter = factory(values)
        except (ContractError, SidecarRuntimeError, OSError) as error:
            _snapshot = NarrationRuntimeSnapshot(
                technical_enabled=requested,
                lifecycle_status="configuration_error",
                reason_code=_safe_reason(error, "SIDECAR_CONFIGURATION_INVALID"),
            )
            return
        if adapter is None:
            _snapshot = NarrationRuntimeSnapshot()
            return
        _adapter = adapter
        _snapshot = NarrationRuntimeSnapshot(
            technical_enabled=True,
            lifecycle_status="starting",
        )
        _runtime_task = asyncio.create_task(
            _run_runtime(
                adapter,
                product_visible_requested=product_visible_requested,
                lazy_load_requested=not validation_requested,
                idle_unload_seconds=idle_unload_seconds,
            ),
            name="ai-novel-moss-tts-runtime",
        )


async def stop_narration_runtime() -> None:
    """Detach the adapter, stop renewal, and make the Sidecar inert."""

    global _adapter, _runtime_task, _snapshot
    async with _lifecycle_lock:
        adapter = _adapter
        task = _runtime_task
        _adapter = None
        _runtime_task = None
        _snapshot = NarrationRuntimeSnapshot(lifecycle_status="stopping")
    if task is not None and task is not asyncio.current_task():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    reason_code: str | None = None
    if adapter is not None:
        try:
            await adapter.deactivate()
        except (SidecarRuntimeError, OSError, TimeoutError) as error:
            reason_code = _safe_reason(error, "SIDECAR_DEACTIVATE_FAILED")
    async with _lifecycle_lock:
        _snapshot = NarrationRuntimeSnapshot(
            lifecycle_status=(
                "disabled" if reason_code is None else "disabled_watchdog_pending"
            ),
            reason_code=reason_code,
        )


async def wait_narration_runtime_initialized(timeout_seconds: float = 180.0) -> None:
    """Gate/test helper; production requests should read the status snapshot."""

    async with _lifecycle_lock:
        task = _runtime_task
    if task is None:
        return
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        state = narration_runtime_status()["lifecycle_status"]
        if state in {"ready", "unavailable", "configuration_error", "disabled"}:
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("narration runtime initialization did not settle")


__all__ = [
    "DEFAULT_IDLE_UNLOAD_SECONDS",
    "IDLE_UNLOAD_SECONDS_ENV",
    "MAX_IDLE_UNLOAD_SECONDS",
    "MIN_IDLE_UNLOAD_SECONDS",
    "NarrationRuntimeSnapshot",
    "PRODUCT_ENABLE_ENV",
    "get_ready_narration_adapter",
    "launch_narration_runtime",
    "narration_runtime_status",
    "stop_narration_runtime",
    "wait_narration_runtime_initialized",
]
