from __future__ import annotations

import asyncio
import importlib
from typing import Callable

import pytest
import pytest_asyncio

from backend.narration.contracts import AdapterHealth, AdapterHealthStatus
from backend.narration.runtime import (
    CAPABILITIES_SHA256,
    SidecarRuntimeError,
)
import backend.narration.pawapp_runtime as pawapp_runtime_module
import backend.narration.runtime as sidecar_runtime_module


MODEL_FINGERPRINT_SHA256 = "b" * 64
RUNTIME_TASK_NAME = "ai-novel-moss-tts-runtime"


class ControlledAdapter:
    def __init__(
        self,
        *,
        activation_gate: asyncio.Event | None = None,
        warmup_gate: asyncio.Event | None = None,
        fail_phase: str | None = None,
        deactivate_error: bool = False,
        on_deactivate: Callable[[], None] | None = None,
    ):
        self.activation_gate = activation_gate
        self.warmup_gate = warmup_gate
        self.fail_phase = fail_phase
        self.deactivate_error = deactivate_error
        self.on_deactivate = on_deactivate
        self.calls: list[str] = []
        self.worker_generation = 41
        self.lease_generation = 7
        self.renew_count = 0
        self.deactivate_count = 0
        self.renewed = asyncio.Event()
        self.deactivated = asyncio.Event()
        self.warmup_started = asyncio.Event()
        self.warmup_cancelled = asyncio.Event()
        self.warmup_count = 0

    async def activate(self) -> int:
        self.calls.append("activate")
        if self.activation_gate is not None:
            await self.activation_gate.wait()
        self._raise_if("activate")
        return self.lease_generation

    async def health(self) -> AdapterHealth:
        self.calls.append("health")
        self._raise_if("health")
        return AdapterHealth(
            AdapterHealthStatus.DEGRADED,
            CAPABILITIES_SHA256,
            None,
        )

    async def warmup(self) -> AdapterHealth:
        self.calls.append("warmup")
        self.warmup_count += 1
        self.warmup_started.set()
        try:
            if self.warmup_gate is not None:
                await self.warmup_gate.wait()
            self._raise_if("warmup")
        except asyncio.CancelledError:
            self.warmup_cancelled.set()
            raise
        return AdapterHealth(
            AdapterHealthStatus.HEALTHY,
            CAPABILITIES_SHA256,
            MODEL_FINGERPRINT_SHA256,
        )

    async def renew_lease(self) -> int:
        self.calls.append("renew")
        self._raise_if("renew")
        self.renew_count += 1
        self.renewed.set()
        return self.lease_generation

    async def deactivate(self) -> None:
        self.calls.append("deactivate")
        self.deactivate_count += 1
        if self.on_deactivate is not None:
            self.on_deactivate()
        self.deactivated.set()
        if self.deactivate_error:
            raise SidecarRuntimeError(
                "TEST_DEACTIVATE_FAILED",
                "controlled fake deactivate failure",
            )

    def _raise_if(self, phase: str) -> None:
        if self.fail_phase == phase:
            raise SidecarRuntimeError(
                f"TEST_{phase.upper()}_FAILED",
                "controlled fake lifecycle failure",
            )


@pytest_asyncio.fixture
async def runtime_owner():
    module = importlib.reload(pawapp_runtime_module)
    yield module
    await module.stop_narration_runtime()
    await asyncio.sleep(0)
    leaked = [
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not task.done()
        and task.get_name() == RUNTIME_TASK_NAME
    ]
    assert leaked == []


def _factory(adapter: ControlledAdapter):
    calls: list[dict[str, str]] = []

    def build(environ):  # noqa: ANN001
        calls.append(dict(environ or {}))
        return adapter

    return calls, build


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 1.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition did not settle before timeout")


@pytest.mark.asyncio
async def test_disabled_factory_returns_before_token_or_http(
    runtime_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_reads = 0
    http_connections = 0
    factory_calls: list[dict[str, str]] = []

    def forbidden_token_read(*_args, **_kwargs):  # noqa: ANN002, ANN003
        nonlocal token_reads
        token_reads += 1
        raise AssertionError("disabled runtime read a bootstrap token")

    def forbidden_http(*_args, **_kwargs):  # noqa: ANN002, ANN003
        nonlocal http_connections
        http_connections += 1
        raise AssertionError("disabled runtime attempted Sidecar HTTP")

    monkeypatch.setattr(sidecar_runtime_module, "read_secret_token", forbidden_token_read)
    monkeypatch.setattr(sidecar_runtime_module, "HTTPConnection", forbidden_http)

    def production_factory(environ):  # noqa: ANN001
        factory_calls.append(dict(environ or {}))
        return sidecar_runtime_module.build_moss_adapter_from_environment(environ)

    await runtime_owner.launch_narration_runtime(
        {"AI_NOVEL_TTS_RUNTIME_ENABLED": "false"},
        factory=production_factory,
    )

    assert factory_calls == [{"AI_NOVEL_TTS_RUNTIME_ENABLED": "false"}]
    assert token_reads == 0
    assert http_connections == 0
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status() == {
        "technical_enabled": False,
        "lifecycle_status": "disabled",
        "sidecar_reachable": False,
        "model_ready": False,
        "product_visible": False,
        "protocol_version": "moss-tts-sidecar/1.1",
        "worker_generation": None,
        "lease_generation": None,
        "model_fingerprint_sha256": None,
        "reason_code": None,
    }


@pytest.mark.asyncio
async def test_disabled_runtime_never_exposes_product_even_when_product_was_requested(
    runtime_owner,
) -> None:
    await runtime_owner.launch_narration_runtime(
        {
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "false",
            "AI_NOVEL_TTS_PRODUCT_ENABLED": "true",
        },
        factory=lambda _environ: None,
    )

    status = runtime_owner.narration_runtime_status()
    assert status["lifecycle_status"] == "disabled"
    assert status["model_ready"] is False
    assert status["product_visible"] is False


@pytest.mark.asyncio
async def test_enabled_launch_is_nonblocking_then_becomes_ready_and_renews(
    runtime_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation_gate = asyncio.Event()
    adapter = ControlledAdapter(activation_gate=activation_gate)
    factory_calls, factory = _factory(adapter)
    monkeypatch.setattr(
        runtime_owner,
        "WORKER_LEASE_RENEW_INTERVAL_SECONDS",
        0.01,
    )

    await asyncio.wait_for(
        runtime_owner.launch_narration_runtime(
            {"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"},
            factory=factory,
        ),
        timeout=0.1,
    )
    assert factory_calls == [{"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"}]
    await _wait_until(lambda: adapter.calls == ["activate"])
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "starting"

    unrelated_turn_completed = False

    async def unrelated_host_turn() -> None:
        nonlocal unrelated_turn_completed
        await asyncio.sleep(0)
        unrelated_turn_completed = True

    await asyncio.wait_for(unrelated_host_turn(), timeout=0.1)
    assert unrelated_turn_completed is True

    activation_gate.set()
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)
    await asyncio.wait_for(adapter.renewed.wait(), timeout=1)

    status = runtime_owner.narration_runtime_status()
    assert adapter.calls[:3] == ["activate", "health", "warmup"]
    assert adapter.renew_count >= 1
    assert runtime_owner.get_ready_narration_adapter() is adapter
    assert status == {
        "technical_enabled": True,
        "lifecycle_status": "ready",
        "sidecar_reachable": True,
        "model_ready": True,
        "product_visible": False,
        "protocol_version": "moss-tts-sidecar/1.1",
        "worker_generation": 41,
        "lease_generation": 7,
        "model_fingerprint_sha256": MODEL_FINGERPRINT_SHA256,
        "reason_code": None,
    }
    assert not ({"token", "path", "host", "port"} & set(status))
    assert all(
        marker not in str(status).lower()
        for marker in (
            "moss_tts_sidecar_token",
            "/run/secrets",
            "x-moss-sidecar-token",
            "x-moss-worker-token",
        )
    )


@pytest.mark.asyncio
async def test_long_warmup_renews_lease_without_exposing_adapter(
    runtime_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmup_gate = asyncio.Event()
    adapter = ControlledAdapter(warmup_gate=warmup_gate)
    _, factory = _factory(adapter)
    monkeypatch.setattr(
        runtime_owner,
        "WORKER_LEASE_RENEW_INTERVAL_SECONDS",
        0.01,
    )

    await runtime_owner.launch_narration_runtime(
        {"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"},
        factory=factory,
    )
    await asyncio.wait_for(adapter.warmup_started.wait(), timeout=1)
    await asyncio.wait_for(adapter.renewed.wait(), timeout=1)

    assert adapter.warmup_count == 1
    assert adapter.renew_count >= 1
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "starting"

    warmup_gate.set()
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)

    assert runtime_owner.get_ready_narration_adapter() is adapter
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "ready"


@pytest.mark.asyncio
async def test_warmup_renewal_failure_cancels_warmup_and_deactivates(
    runtime_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmup_gate = asyncio.Event()
    adapter = ControlledAdapter(warmup_gate=warmup_gate, fail_phase="renew")
    _, factory = _factory(adapter)
    monkeypatch.setattr(
        runtime_owner,
        "WORKER_LEASE_RENEW_INTERVAL_SECONDS",
        0.01,
    )

    await runtime_owner.launch_narration_runtime(
        {"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"},
        factory=factory,
    )
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)
    await asyncio.wait_for(adapter.deactivated.wait(), timeout=1)

    assert adapter.warmup_count == 1
    assert adapter.warmup_cancelled.is_set()
    assert adapter.deactivate_count == 1
    assert adapter.calls == ["activate", "health", "warmup", "renew", "deactivate"]
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status()["reason_code"] == (
        "TEST_RENEW_FAILED"
    )


@pytest.mark.asyncio
async def test_stop_during_warmup_cancels_child_and_deactivates_once(
    runtime_owner,
) -> None:
    warmup_gate = asyncio.Event()
    adapter = ControlledAdapter(warmup_gate=warmup_gate)
    _, factory = _factory(adapter)

    await runtime_owner.launch_narration_runtime(
        {"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"},
        factory=factory,
    )
    await asyncio.wait_for(adapter.warmup_started.wait(), timeout=1)

    await runtime_owner.stop_narration_runtime()

    assert adapter.warmup_cancelled.is_set()
    assert adapter.deactivate_count == 1
    assert adapter.calls == ["activate", "health", "warmup", "deactivate"]
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "disabled"


@pytest.mark.asyncio
async def test_product_flag_becomes_visible_only_after_runtime_is_ready(
    runtime_owner,
) -> None:
    activation_gate = asyncio.Event()
    adapter = ControlledAdapter(activation_gate=activation_gate)
    _, factory = _factory(adapter)

    await runtime_owner.launch_narration_runtime(
        {
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
            "AI_NOVEL_TTS_PRODUCT_ENABLED": "true",
        },
        factory=factory,
    )
    await _wait_until(lambda: adapter.calls == ["activate"])
    assert runtime_owner.narration_runtime_status()["product_visible"] is False

    activation_gate.set()
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)
    status = runtime_owner.narration_runtime_status()
    assert status["lifecycle_status"] == "ready"
    assert status["model_ready"] is True
    assert status["product_visible"] is True


@pytest.mark.asyncio
async def test_non_exact_product_flag_stays_hidden_when_runtime_is_ready(
    runtime_owner,
) -> None:
    adapter = ControlledAdapter()
    _, factory = _factory(adapter)

    await runtime_owner.launch_narration_runtime(
        {
            "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
            "AI_NOVEL_TTS_PRODUCT_ENABLED": "TRUE",
        },
        factory=factory,
    )
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)

    status = runtime_owner.narration_runtime_status()
    assert status["lifecycle_status"] == "ready"
    assert status["model_ready"] is True
    assert status["product_visible"] is False


@pytest.mark.asyncio
async def test_stop_detaches_before_deactivate_stops_renewal_and_is_idempotent(
    runtime_owner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detached_observations: list[bool] = []
    adapter = ControlledAdapter(
        on_deactivate=lambda: detached_observations.append(
            runtime_owner.get_ready_narration_adapter() is None
        )
    )
    _, factory = _factory(adapter)
    monkeypatch.setattr(
        runtime_owner,
        "WORKER_LEASE_RENEW_INTERVAL_SECONDS",
        0.01,
    )
    await runtime_owner.launch_narration_runtime(
        {"AI_NOVEL_TTS_RUNTIME_ENABLED": "true"},
        factory=factory,
    )
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)
    await asyncio.wait_for(adapter.renewed.wait(), timeout=1)

    await runtime_owner.stop_narration_runtime()
    renew_count_after_stop = adapter.renew_count
    await asyncio.sleep(0.04)

    assert adapter.deactivate_count == 1
    assert detached_observations == [True]
    assert adapter.renew_count == renew_count_after_stop
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "disabled"

    await runtime_owner.stop_narration_runtime()
    assert adapter.deactivate_count == 1
    assert runtime_owner.narration_runtime_status()["lifecycle_status"] == "disabled"


@pytest.mark.asyncio
async def test_background_failure_degrades_without_failing_host_or_leaking_task(
    runtime_owner,
) -> None:
    adapter = ControlledAdapter(
        fail_phase="warmup",
        deactivate_error=True,
    )
    _, factory = _factory(adapter)

    await asyncio.wait_for(
        runtime_owner.launch_narration_runtime(
            {
                "AI_NOVEL_TTS_RUNTIME_ENABLED": "true",
                "AI_NOVEL_TTS_PRODUCT_ENABLED": "true",
            },
            factory=factory,
        ),
        timeout=0.1,
    )
    await runtime_owner.wait_narration_runtime_initialized(timeout_seconds=1)
    await asyncio.wait_for(adapter.deactivated.wait(), timeout=1)
    await _wait_until(
        lambda: not any(
            task.get_name() == RUNTIME_TASK_NAME
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        )
    )

    assert adapter.calls == ["activate", "health", "warmup", "deactivate"]
    assert runtime_owner.get_ready_narration_adapter() is None
    assert runtime_owner.narration_runtime_status() == {
        "technical_enabled": True,
        "lifecycle_status": "unavailable",
        "sidecar_reachable": False,
        "model_ready": False,
        "product_visible": False,
        "protocol_version": "moss-tts-sidecar/1.1",
        "worker_generation": None,
        "lease_generation": None,
        "model_fingerprint_sha256": None,
        "reason_code": "TEST_WARMUP_FAILED",
    }
    assert await asyncio.wait_for(asyncio.sleep(0, result="host-alive"), timeout=0.1) == "host-alive"
